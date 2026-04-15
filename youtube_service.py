import os
import re
import pandas as pd
from googleapiclient.discovery import build

def get_youtube_client():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY .env dosyasında bulunamadı!")
    return build('youtube', 'v3', developerKey=api_key)

def extract_video_id(url: str):
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1][:11]
    return None

def get_video_title(video_url: str) -> str:
    video_id = extract_video_id(video_url)
    if not video_id: return None
    try:
        youtube = get_youtube_client()
        request = youtube.videos().list(part="snippet", id=video_id)
        response = request.execute()
        if response.get("items"):
            return response["items"][0]["snippet"]["title"]
    except Exception:
        pass
    return None


# --- 1. TÜRKÇE DUYGU ANALİZİ (Leksikon tabanlı) ---
_POZITIF_KELIMELER = {
    "harika", "mükemmel", "süper", "enfes", "güzel", "iyi", "sevdim", "beğendim",
    "teşekkür", "teşekkürler", "sağol", "sağolun", "bravo", "tebrikler", "efsane",
    "muhteşem", "başarılı", "başarılı", "kaliteli", "seviyorum", "bayıldım",
    "harikulade", "nefis", "şahane", "memnun", "memnunum", "memnuniyetle",
    "faydalı", "yararlı", "bilgilendirici", "açıklayıcı", "net", "anlaşılır",
    "devam", "devamını", "bekliyorum", "takip", "abone", "izledim", "izliyorum",
    "tavsiye", "öneririm", "kesinlikle", "mutlaka", "doğru", "haklısın",
    "katılıyorum", "evet", "gerçekten", "sahiden", "vay", "vay be", "helal",
    "alkış", "👏", "❤️", "🔥", "😍", "👍", "💯", "🙏", "✅", "😊", "🥰",
    "emek", "emeğine", "zahmet", "güldüm", "eğlenceli", "komik", "güldürdü",
}

_NEGATIF_KELIMELER = {
    "kötü", "berbat", "rezalet", "rezil", "saçma", "saçmalık", "yanlış",
    "hata", "hatalı", "eksik", "yetersiz", "beğenmedim", "sevmedim", "olmamış",
    "olmaz", "olmadı", "napalım", "boş", "işe yaramaz", "vakit kaybı",
    "abartı", "abartıyor", "yalan", "yanıltıcı", "aldatıcı", "şüpheli",
    "kötüleşti", "bozuk", "çalışmıyor", "sorun", "sorunlu", "problem",
    "şikayet", "şikayetim", "beğenmedim", "izlemedim", "izlemeyeceğim",
    "neden", "nasıl böyle", "anlamadım", "karmaşık", "zor", "sıkıcı",
    "uzun", "gereksiz", "aboneliği", "iptal", "bıktım", "usandım",
    "hayal kırıklığı", "hayal kırıklığına", "üzüldüm", "yazık", "ayıp",
    "utanç", "rezillik", "acınası", "komedi", "gülünç", "saçma sapan",
    "😡", "👎", "💩", "🤢", "😤", "😠", "🙄", "😒", "❌",
}

def turkish_sentiment(text: str) -> str:
    """Türkçe leksikon tabanlı duygu analizi."""
    text_lower = str(text).lower()
    words = re.findall(r'\w+', text_lower)
    emoji_chars = list(text)

    pos_score = sum(1 for w in words if w in _POZITIF_KELIMELER)
    neg_score = sum(1 for w in words if w in _NEGATIF_KELIMELER)

    # Emoji kontrolü
    for ch in emoji_chars:
        if ch in _POZITIF_KELIMELER: pos_score += 1
        if ch in _NEGATIF_KELIMELER: neg_score += 1

    # Olumsuzlama: "değil", "yok", "hiç" önceki pozitifi iptal eder
    negation_words = {"değil", "yok", "hiç", "olmaz", "olmadı", "hayır"}
    for i, w in enumerate(words):
        if w in negation_words and i > 0 and words[i-1] in _POZITIF_KELIMELER:
            pos_score = max(0, pos_score - 2)
            neg_score += 1

    if pos_score > neg_score:
        return "olumlu"
    elif neg_score > pos_score:
        return "olumsuz"
    else:
        return "notr"


# --- 2. GENİŞLETİLMİŞ KÜFÜR TESPİTİ ---
_KUFUR_LISTESI = [
    # Temel
    "amk", "amına", "amını", "bok", "boktan", "orospu", "orospuçocuğu",
    "sik", "sikiş", "sikik", "siktir", "sikerim", "sikicem", "sikeyim",
    "yarrak", "göt", "götüm", "götveren", "götlek",
    "piç", "piçi", "piçler", "piçlik",
    "ibne", "ibnelik",
    "oç", "sg", "aq",
    "pezevenk", "pezevengi",
    "yavşak", "namussuz", "orspu",
    "kahpe", "kahpenin", "kaltak",
    "gerizekalı", "geri zekalı", "aptal", "salak", "dangalak", "ahmak",
    "mal", "malın", "manyak", "deli",
    "haysiyetsiz", "şerefsiz", "şerefsizin",
    "it", "köpek", "eşek", "eşşek", "katır",
    # Kısaltmalar ve varyasyonlar
    "amq", "orosbuçocuğu", "orsbuçocuğu", "s1k", "s!k",
]

def extract_profanity(text: str):
    escaped = [re.escape(w) for w in _KUFUR_LISTESI]
    # (?<!\w) ve (?!\w) ile tam kelime eşleşmesi — "amcana" içindeki "am" eşleşmez
    pattern = r'(?<!\w)(' + '|'.join(escaped) + r')(?!\w)'
    matches = re.findall(pattern, str(text), re.IGNORECASE)
    return list(set(m.lower() for m in matches)) if matches else []


# --- 3. GELİŞTİRİLMİŞ ÖNERİ/ELEŞTİRİ TESPİTİ ---
_ONERI_KALIPLARI = [
    r'\bbence\b', r'\bbana göre\b', r'\btavsiye\b', r'\böneri\b', r'\bönerim\b',
    r'\bkeşke\b', r'\bolsa iyi olur\b', r'\byapılabilir\b', r'\byapılsa\b',
    r'\bekliyoruz\b', r'\bekliyorum\b', r'\bistiyorum\b', r'\bistiyoruz\b',
    r'\bdaha iyi\b', r'\bdaha güzel\b', r'\bdaha net\b', r'\bdaha açık\b',
    r'\böneriyorum\b', r'\bönerim var\b', r'\bönerim\b',
    r'\bkatılıyorum\b', r'\bhaklısın\b', r'\bdoğru söylüyorsun\b',
    r'\byani\b.{0,20}\bolsa\b', r'\bşöyle olsa\b', r'\bşunu yapsan\b',
]

_ELESTIRI_KALIPLARI = [
    r'\bdüzelt\b', r'\bdüzeltilmeli\b', r'\beleştiri\b', r'\beleştiriyorum\b',
    r'\bolmamış\b', r'\bolmadı\b', r'\bberbat\b', r'\bkötü\b', r'\brezalet\b',
    r'\byalan\b', r'\byanıltıcı\b', r'\bsatılmış\b', r'\btaraflı\b',
    r'\beksik\b', r'\byetersiz\b', r'\bhatalı\b', r'\byanlış\b',
    r'\bşikayet\b', r'\bsorun var\b', r'\bproblem var\b',
    r'\bneden böyle\b', r'\bnasıl böyle\b', r'\banlamıyorum\b',
    r'\bhayal kırıklığı\b', r'\büzüldüm\b', r'\bazıp\b', r'\bayıp\b',
    r'\bbeğenmedim\b', r'\bsevmedim\b', r'\bişe yaramaz\b',
]

def get_feedback_type(text: str):
    t = str(text)
    for pattern in _ELESTIRI_KALIPLARI:
        if re.search(pattern, t, re.IGNORECASE):
            return 'eleştiri'
    for pattern in _ONERI_KALIPLARI:
        if re.search(pattern, t, re.IGNORECASE):
            return 'öneri'
    return None

def format_percentage(part, whole):
    if whole == 0: return "0%"
    return f"{round((part / whole) * 100, 1)}%"

def fetch_and_generate_raw_report(video_url: str, output_path: str, max_comments: int = 5000):
    video_id = extract_video_id(video_url)
    if not video_id:
        raise ValueError("Geçersiz YouTube URL'si: Video ID bulunamadı.")

    youtube = get_youtube_client()
    comments_data = []
    seen_ids = set()  # ID bazlı dedup — metin bazlı değil

    def parse_comment(snippet):
        text = snippet["textDisplay"]
        return {
            "kullanici": snippet["authorDisplayName"],
            "yorum": text,
            "begeni_sayisi": int(snippet["likeCount"]),
            "duygu": turkish_sentiment(text),
            "tarih": snippet["publishedAt"][:10],
            "_kufur_listesi": extract_profanity(text),
            "_feedback_type": get_feedback_type(text)
        }

    try:
        # --- Aşama 1: Tüm üst düzey thread'leri çek ---
        threads_with_replies = []  # yanıtı olan thread ID'leri

        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            textFormat="plainText"
        )

        while request and len(comments_data) < max_comments:
            response = request.execute()

            for item in response.get("items", []):
                thread_id = item["id"]
                if thread_id in seen_ids:
                    continue
                seen_ids.add(thread_id)

                top_snippet = item["snippet"]["topLevelComment"]["snippet"]
                comments_data.append(parse_comment(top_snippet))

                reply_count = item["snippet"].get("totalReplyCount", 0)
                if reply_count > 0:
                    threads_with_replies.append(thread_id)

            request = youtube.commentThreads().list_next(request, response)

        # --- Aşama 2: Her thread için TÜM yanıtları çek (5+ dahil) ---
        for thread_id in threads_with_replies:
            if len(comments_data) >= max_comments:
                break
            try:
                reply_request = youtube.comments().list(
                    part="snippet",
                    parentId=thread_id,
                    maxResults=100,
                    textFormat="plainText"
                )
                while reply_request and len(comments_data) < max_comments:
                    reply_response = reply_request.execute()
                    for r in reply_response.get("items", []):
                        cid = r["id"]
                        if cid not in seen_ids:
                            seen_ids.add(cid)
                            comments_data.append(parse_comment(r["snippet"]))
                    reply_request = youtube.comments().list_next(reply_request, reply_response)
            except Exception:
                pass

    except Exception as e:
        raise Exception(f"YouTube Veri Çekme Hatası: {str(e)}")

    if not comments_data:
        raise Exception("Hiç yorum bulunamadı veya videonun yorumları kapalı.")

    df = pd.DataFrame(comments_data)
    
    total_comments = len(df)
    total_likes = df['begeni_sayisi'].sum()
    avg_likes = total_likes / total_comments if total_comments > 0 else 0
    
    sentiment_counts = df['duygu'].value_counts().to_dict()
    olumlu_count = sentiment_counts.get('olumlu', 0)
    olumsuz_count = sentiment_counts.get('olumsuz', 0)
    notr_count = sentiment_counts.get('notr', 0)
    
    profane_total = df['_kufur_listesi'].apply(lambda x: len(x) > 0).sum()

    stats_data = [
        {"Metrik": "Toplam Yorum", "Sayı": int(total_comments), "Yüzde": "100%"},
        {"Metrik": "Olumlu Yorum", "Sayı": int(olumlu_count), "Yüzde": format_percentage(olumlu_count, total_comments)},
        {"Metrik": "Olumsuz Yorum", "Sayı": int(olumsuz_count), "Yüzde": format_percentage(olumsuz_count, total_comments)},
        {"Metrik": "Nötr Yorum", "Sayı": int(notr_count), "Yüzde": format_percentage(notr_count, total_comments)},
        {"Metrik": "Küfür İçeren", "Sayı": int(profane_total), "Yüzde": format_percentage(profane_total, total_comments)},
        {"Metrik": "Ortalama Beğeni", "Sayı": round(avg_likes, 1), "Yüzde": "-"},
        {"Metrik": "Toplam Beğeni", "Sayı": int(total_likes), "Yüzde": "-"}
    ]
    df_stats = pd.DataFrame(stats_data)

    df_profane_full = df[df['_kufur_listesi'].apply(len) > 0].copy()
    if len(df_profane_full) > 0:
        df_profane_full['kufur_kelimeleri'] = df_profane_full['_kufur_listesi'].astype(str)
        df_profane = df_profane_full[['kullanici', 'yorum', 'kufur_kelimeleri', 'begeni_sayisi']]
    else:
        df_profane_empty = pd.DataFrame([{"kullanici": "-", "yorum": "-", "kufur_kelimeleri": "[]", "begeni_sayisi": 0}])
        df_profane = df_profane_empty[['kullanici', 'yorum', 'kufur_kelimeleri', 'begeni_sayisi']]

    df_top_liked = df.sort_values(by='begeni_sayisi', ascending=False).head(100)
    df_top_liked = df_top_liked[['kullanici', 'yorum', 'begeni_sayisi', 'duygu', 'tarih']]

    df_sentiment_dist = df.groupby('duygu').agg(
        yorum_sayisi=('yorum', 'count'),
        toplam_begeni=('begeni_sayisi', 'sum')
    ).reset_index()

    sugg_list = df[df['_feedback_type'] == 'öneri']['yorum'].value_counts().reset_index()
    crit_list = df[df['_feedback_type'] == 'eleştiri']['yorum'].value_counts().reset_index()
    
    sugg_list.columns = ['Öneri', 'Tekrar Sayısı']
    crit_list.columns = ['Eleştiri', 'Tekrar Sayısı']
    
    # Çok uzun olanları formatı bozmaması için sınırla
    if not sugg_list.empty:
        sugg_list['Öneri'] = sugg_list['Öneri'].apply(lambda x: x[:100] + '...' if len(str(x)) > 100 else x)
    if not crit_list.empty:
        crit_list['Eleştiri'] = crit_list['Eleştiri'].apply(lambda x: x[:100] + '...' if len(str(x)) > 100 else x)
    
    df_feedback_summary = pd.concat([sugg_list, crit_list], axis=1)

    df_main = df[['kullanici', 'yorum', 'begeni_sayisi', 'duygu', 'tarih']]

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df_main.to_excel(writer, sheet_name='Tum Yorumlar', index=False)
        df_stats.to_excel(writer, sheet_name='Istatistikler', index=False)
        df_profane.to_excel(writer, sheet_name='Kufur Iceren Yorumlar', index=False)
        df_top_liked.to_excel(writer, sheet_name='En Begilen Yorumlar', index=False)
        
        if len(df_feedback_summary) > 0:
            df_feedback_summary.to_excel(writer, sheet_name='Oneri_Elestiri_Ozeti', index=False)
        else:
            pd.DataFrame(columns=['Öneri', 'Tekrar Sayısı', 'Eleştiri', 'Tekrar Sayısı']).to_excel(writer, sheet_name='Oneri_Elestiri_Ozeti', index=False)
            
        df_sentiment_dist.to_excel(writer, sheet_name='Duygu_Dagilimi', index=False)
    
    return True
