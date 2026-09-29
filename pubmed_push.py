import os
import json
import time
import smtplib
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header
from xml.etree import ElementTree as ET

# 如果本地运行，可以直接改下面默认值；GitHub 上会从 Secrets 读取
SENDER = os.getenv("SENDER_EMAIL", "你的QQ邮箱@qq.com")
PASSWORD = os.getenv("SENDER_PASSWORD", "你的QQ邮箱授权码")
RECEIVER = os.getenv("RECEIVER_EMAIL", SENDER)
API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", SENDER)

SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SEEN_FILE = "seen_pmids.json"


def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f).get("pmids", []))
        except Exception:
            return set()
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump({"pmids": list(seen)[-5000:]}, f, ensure_ascii=False)


def search_pubmed():
    year = datetime.now().year

    query = (
        '("obesity"[mh] OR obesity[tiab] OR obese[tiab] OR overweight[tiab]) '
        'AND '
        '("hypertension"[mh] OR hypertension[tiab] OR "high blood pressure"[tiab]) '
        'AND '
        '("myocardial remodeling"[tiab] OR "cardiac remodeling"[tiab] '
        'OR "ventricular remodeling"[tiab] OR "myocardial fibrosis"[tiab] '
        'OR "cardiac hypertrophy"[tiab] OR "myocardial remodelling"[tiab]) '
        f'AND ({year}[dp] : 3000[dp])'
    )

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": 20,
        "sort": "pub+date",
        "retmode": "json",
    }
    if API_KEY:
        params["api_key"] = API_KEY
    if NCBI_EMAIL:
        params["email"] = NCBI_EMAIL

    r = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    ids = r.json().get("esearchresult", {}).get("idlist", [])

    if not ids:
        return []

    time.sleep(0.5)

    params2 = {
        "db": "pubmed",
        "id": ",".join(ids),
        "rettype": "abstract",
        "retmode": "xml",
    }
    if API_KEY:
        params2["api_key"] = API_KEY
    if NCBI_EMAIL:
        params2["email"] = NCBI_EMAIL

    r2 = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params=params2,
        timeout=60,
    )
    r2.raise_for_status()

    root = ET.fromstring(r2.text)
    articles = []

    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID", "")
        title = art.findtext(".//ArticleTitle", "无标题")
        journal = art.findtext(".//Journal/Title", "")
        date = art.findtext(".//PubDate/Year", "")

        authors = []
        for a in art.findall(".//Author"):
            last = a.findtext("LastName", "")
            fore = a.findtext("ForeName", "")
            if last:
                authors.append(f"{fore} {last}".strip())

        abstract = " ".join(
            [t.text or "" for t in art.findall(".//AbstractText")]
        )
        if not abstract:
            abstract = "无摘要"

        articles.append({
            "pmid": pmid,
            "title": title,
            "journal": journal,
            "date": date,
            "authors": authors,
            "abstract": abstract,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })

    return articles


def send_email(articles):
    today = datetime.now().strftime("%Y-%m-%d")

    html = f"<h2>PubMed 新文献 {today}，共 {len(articles)} 篇</h2>"

    for i, a in enumerate(articles, 1):
        authors = ", ".join(a["authors"][:5])
        if len(a["authors"]) > 5:
            authors += " et al."

        html += (
            f"<hr>"
            f"<b>{i}. {a['title']}</b><br>"
            f"{authors}<br>"
            f"{a['journal']} {a['date']}<br>"
            f"<a href='{a['url']}'>PubMed 链接</a>"
            f"<p>{a['abstract'][:800]}</p>"
        )

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = Header(f"PubMed推送 {today} 共{len(articles)}篇", "utf-8")
    msg["From"] = SENDER
    msg["To"] = RECEIVER

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, [RECEIVER], msg.as_string())


def main():
    seen = load_seen()
    articles = search_pubmed()
    new_articles = [a for a in articles if a["pmid"] not in seen]

    if not new_articles:
        print("没有新文章")
        return

    send_email(new_articles)

    for a in new_articles:
        seen.add(a["pmid"])
    save_seen(seen)

    print(f"已发送 {len(new_articles)} 篇")


if __name__ == "__main__":
    main()
