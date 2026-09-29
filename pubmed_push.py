import os
import json
import time
import smtplib
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header
from xml.etree import ElementTree as ET

# ==================== 配置 ====================
SENDER = os.getenv("SENDER_EMAIL", "你的QQ邮箱@qq.com")
PASSWORD = os.getenv("SENDER_PASSWORD", "你的QQ邮箱授权码")
RECEIVER = os.getenv("RECEIVER_EMAIL", SENDER)
API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", SENDER)

SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SEEN_FILE = "seen_pmids.json"

# ==================== 期刊名单 (IF >= 10) ====================
# 是否包含中医/补充替代医学期刊
INCLUDE_TCM_JOURNALS = True

# 心血管领域
CARDIO_JOURNALS = [
    "Nature Reviews Cardiology", "European Heart Journal", "Circulation",
    "Journal of the American College of Cardiology", "JACC",
    "Circulation Research", "Cardiovascular Diabetology",
    "JACC: CardioOncology", "JAMA Cardiology", "Cardiovascular Research",
    "Progress in Cardiovascular Diseases", "European Journal of Heart Failure",
    "Europace", "European Journal of Preventive Cardiology",
    "JACC: Cardiovascular Imaging", "JACC: Heart Failure",
    "JACC: Cardiovascular Interventions",
]

# 内分泌与代谢领域
ENDO_JOURNALS = [
    "Nature Reviews Endocrinology", "Cell Metabolism",
    "The Lancet Diabetes & Endocrinology", "Nature Metabolism",
    "Endocrine Reviews", "Diabetes Care",
    "Trends in Endocrinology & Metabolism", "Current Obesity Reports",
    "Metabolism - Clinical and Experimental",
    "Journal of Obesity & Metabolic Syndrome", "Diabetologia",
]

# 中医与补充替代医学领域
TCM_JOURNALS = [
    "Phytomedicine", "Chinese Herbal Medicines",
    "Journal of Ethnopharmacology", "Chinese Medicine",
    "Phytotherapy Research", "Journal of Traditional Chinese Medicine",
    "Journal of Integrative Medicine",
]

# 合并期刊列表
HIGH_IF_JOURNALS = CARDIO_JOURNALS + ENDO_JOURNALS
if INCLUDE_TCM_JOURNALS:
    HIGH_IF_JOURNALS += TCM_JOURNALS

# ==================== 基础功能 ====================
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

def is_high_if_journal(journal_name):
    """判断期刊是否在影响因子>=10的名单中"""
    if not journal_name:
        return False
    journal_upper = journal_name.upper()
    for keyword in HIGH_IF_JOURNALS:
        if keyword.upper() in journal_upper:
            return True
    return False

# ==================== PubMed 检索 ====================
def search_pubmed():
    year = datetime.now().year

    # ---- 主题检索式：肥胖 + 高血压 + 心肌重构 ----
    query = (
        '("Obesity"[Mesh] OR "Obesity, Abdominal"[Mesh] OR "Obesity, Morbid"[Mesh] '
        'OR "Overweight"[Mesh] OR "Body Mass Index"[Mesh] '
        'OR obes*[tiab] OR overweight[tiab] OR "body mass index"[tiab] '
        'OR "abdominal obesity"[tiab] OR "central obesity"[tiab] OR adipos*[tiab]) '
        'AND '
        '("Hypertension"[Mesh] OR "Essential Hypertension"[Mesh] OR "Blood Pressure"[Mesh] '
        'OR hypertension[tiab] OR "high blood pressure"[tiab] '
        'OR "elevated blood pressure"[tiab] OR hypertensive[tiab]) '
        'AND '
        '("Ventricular Remodeling"[Mesh] OR "Cardiac Remodeling, Ventricular"[Mesh] '
        'OR "Myocardial Fibrosis"[Mesh] OR "Cardiomegaly"[Mesh] '
        'OR "Hypertrophy, Left Ventricular"[Mesh] '
        'OR "myocardial remodeling"[tiab] OR "cardiac remodeling"[tiab] '
        'OR "ventricular remodeling"[tiab] OR "myocardial fibrosis"[tiab] '
        'OR "cardiac hypertrophy"[tiab] OR "myocardial remodelling"[tiab] '
        'OR "cardiac fibrosis"[tiab] OR "left ventricular hypertrophy"[tiab]) '
        'AND ('
        '"Obesity/complications"[Mesh] OR "Hypertension/complications"[Mesh] '
        'OR "Metabolic Syndrome"[Mesh] OR "comorbidity"[Mesh] '
        'OR comorbid*[tiab] OR "obesity-induced"[tiab] OR "hypertension-induced"[tiab] '
        'OR "obesity-related"[tiab] OR "hypertension-related"[tiab] '
        'OR "obesity-associated"[tiab] OR "hypertension-associated"[tiab]'
        ') '
        'AND ('
        '"animal experimentation"[MeSH Terms] OR "models, animal"[MeSH Terms] '
        'OR "Animals"[Mesh:noexp] OR "mice"[tiab] OR "mouse"[tiab] OR "murine"[tiab] '
        'OR "rats"[tiab] OR "rat"[tiab] OR "rodent"[tiab] OR "rodents"[tiab] '
        'OR "in vitro"[tiab] OR "in vivo"[tiab] OR "cell culture"[tiab] '
        'OR "cardiomyocyte"[tiab] OR "cardiomyocytes"[tiab] OR "fibroblast"[tiab] '
        'OR "fibroblasts"[tiab] OR "molecular mechanism"[tiab] '
        'OR "signaling pathway"[tiab] OR "signal transduction"[tiab] '
        'OR "gene expression"[tiab] OR "protein expression"[tiab] '
        'OR "oxidative stress"[tiab] OR "apoptosis"[tiab] OR "autophagy"[tiab] '
        'OR "inflammation"[tiab]'
        ') '
        'NOT ("Review"[pt] OR "Systematic Review"[pt] OR "Meta-Analysis"[pt]) '
        f'AND ({year}[dp] : 3000[dp])'
    )

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": 200,  # 多获取一些，后面再按期刊过滤
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

    # ---- 按影响因子>=10的期刊过滤 ----
    high_if_articles = [a for a in articles if is_high_if_journal(a["journal"])]

    print(f"检索到 {len(articles)} 篇基础研究，其中 {len(high_if_articles)} 篇发表在影响因子>=10的期刊")
    for a in high_if_articles:
        print(f"  - {a['journal']}: {a['title'][:60]}")

    return high_if_articles

# ==================== 邮件发送 ====================
def send_email(articles):
    today = datetime.now().strftime("%Y-%m-%d")
    tcm_note = "（含中医期刊）" if INCLUDE_TCM_JOURNALS else ""
    html = f"<h2>PubMed 新文献 {today}，共 {len(articles)} 篇（基础研究，IF>=10）{tcm_note}</h2>"

    for i, a in enumerate(articles, 1):
        authors = ", ".join(a["authors"][:5])
        if len(a["authors"]) > 5:
            authors += " et al."

        html += (
            f"<hr>"
            f"<b>{i}. {a['title']}</b><br>"
            f"<b>期刊：</b>{a['journal']}<br>"
            f"{authors}<br>"
            f"{a['date']}<br>"
            f"<a href='{a['url']}'>PubMed 链接</a>"
            f"<p>{a['abstract'][:800]}</p>"
        )

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = Header(f"PubMed推送 {today} 共{len(articles)}篇（IF>=10）", "utf-8")
    msg["From"] = SENDER
    msg["To"] = RECEIVER

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, [RECEIVER], msg.as_string())

# ==================== 主流程 ====================
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
