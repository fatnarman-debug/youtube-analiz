import os
import re
import pandas as pd
from googleapiclient.discovery import build
from textblob import TextBlob
import datetime

def get_youtube_client():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY .env dosyasında bulunamadı!")
    return build('youtube', 'v3', developerKey=api_key)

def extract_video_id(url: str):
    """Farklı YouTube link yapılarından Video ID'sini çıkarır."""
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    
    # Kısaltılmış youtu.be formatı için
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1][:11]
    return None

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

                # Basit duygu analizi (TextBlob İngilizce ağırlıklı çalışır, demo amaçlı ekleniyor)
                analysis = TextBlob(text)
                polarity = analysis.sentiment.polarity
                if polarity > 0.1:
                    sentiment = "Pozitif"
                elif polarity < -0.1:
                    sentiment = "Negatif"
                else:
                    sentiment = "Nötr"

                comments_data.append({
                    "Yazar": author,
                    "Yorum": text,
                    "Tarih": date[:10], # Sadece YYYY-MM-DD
                    "Beğeni": likes,
                    "Sistem Tahmini": sentiment,
                    "Polarity Skoru": round(polarity, 2)
                })

            # Bir sonraki sayfaya geç
            request = youtube.commentThreads().list_next(request, response)
            
    except Exception as e:
        raise Exception(f"YouTube Veri Çekme Hatası: {str(e)}")

    if not comments_data:
        raise Exception("Hiç yorum bulunamadı veya videonun yorumları kapalı.")

    # Pandas ile Excel'e dönüştür
    df = pd.DataFrame(comments_data)
    df.to_excel(output_path, index=False)
    
    return True
