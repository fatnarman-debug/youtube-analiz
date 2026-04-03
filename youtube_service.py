import os
import re
import pandas as pd
from googleapiclient.discovery import build
from textblob import TextBlob

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

def extract_profanity(text: str):
    bad_words = ["amk", "aq", "sg", "siktir", "oç", "piç", "piçi", "piçler", "yavşak", "pezevenk", "göt", "götveren", "götüm", "sik", "sikicem", "ibne", "orospu", "yarrak", "mal", "namussuz"]
    pattern = r'\b(' + '|'.join(bad_words) + r')\b'
    matches = re.findall(pattern, str(text), re.IGNORECASE)
    return list(set(m.lower() for m in matches)) if matches else []

def get_feedback_type(text: str):
    suggestions = ["bence", "tavsiye", "öneri", "keşke", "daha net", "harika", "katılıyorum", "iyi olur"]
    criticisms = ["düzelt", "eleştiri", "olmamış", "berbat", "kötü", "yalan", "taraf", "satılmış"]
    
    s_pattern = r'\b(' + '|'.join(suggestions) + r')\b'
    c_pattern = r'\b(' + '|'.join(criticisms) + r')\b'
    
    if re.search(s_pattern, str(text), re.IGNORECASE): return 'öneri'
    if re.search(c_pattern, str(text), re.IGNORECASE): return 'eleştiri'
    return None

def format_percentage(part, whole):
    if whole == 0: return "0%"
    return f"{round((part / whole) * 100, 1)}%"

def fetch_and_generate_raw_report(video_url: str, output_path: str, max_comments: int = 1000):
    video_id = extract_video_id(video_url)
    if not video_id:
        raise ValueError("Geçersiz YouTube URL'si: Video ID bulunamadı.")

    youtube = get_youtube_client()
    comments_data = []

    try:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            textFormat="plainText"
        )

        while request and len(comments_data) < max_comments:
            response = request.execute()

            for item in response.get("items", []):
                comment = item["snippet"]["topLevelComment"]["snippet"]
                text = comment["textDisplay"]
                author = comment["authorDisplayName"]
                date = comment["publishedAt"]
                likes = comment["likeCount"]

                analysis = TextBlob(text)
                polarity = analysis.sentiment.polarity
                if polarity > 0.1:
                    sentiment = "olumlu"
                elif polarity < -0.1:
                    sentiment = "olumsuz"
                else:
                    sentiment = "notr"

                kufurler = extract_profanity(text)

                comments_data.append({
                    "kullanici": author,
                    "yorum": text,
                    "begeni_sayisi": int(likes),
                    "duygu": sentiment,
                    "tarih": date[:10],
                    "_kufur_listesi": kufurler,
                    "_feedback_type": get_feedback_type(text)
                })

            request = youtube.commentThreads().list_next(request, response)
            
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
