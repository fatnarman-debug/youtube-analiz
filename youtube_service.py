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

def find_profanity(text: str):
    """Küfür tespit eden yardımcı fonksiyon (Kelime bazlı \b regex kullanılır)."""
    # En fazla kullanılanlar eklendi (\b ile kelime içi geçişler filtrelendi, örn: "tamamı" kelimesini yakalamaz)
    bad_words = ["amk", "aq", "sg", "siktir", "oç", "piç", "yavşak", "pezevenk", "göt", "sik", "sikicem", "ibne", "orospu", "yarrak"]
    pattern = r'\b(' + '|'.join(bad_words) + r')\b'
    # re.IGNORECASE ile büyük/küçük harf duyarsız arama
    if re.search(pattern, str(text), re.IGNORECASE):
        return True
    return False

def find_suggestion_criticism(text: str):
    """Öneri ve eleştiri içeren kelimeleri arar."""
    keywords = ["bence", "tavsiye", "öneri", "keşke", "düzelt", "daha net", "eleştiri", "olmamış", "berbat", "harika"]
    pattern = r'\b(' + '|'.join(keywords) + r')\b'
    if re.search(pattern, str(text), re.IGNORECASE):
        return True
    return False

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
                    "Beğeni": int(likes),
                    "Sistem Tahmini": sentiment,
                    "Polarity Skoru": round(polarity, 2)
                })

            # Bir sonraki sayfaya geç
            request = youtube.commentThreads().list_next(request, response)
            
    except Exception as e:
        raise Exception(f"YouTube Veri Çekme Hatası: {str(e)}")

    if not comments_data:
        raise Exception("Hiç yorum bulunamadı veya videonun yorumları kapalı.")

    # 1. Ana Pandas DataFrame (Tum Yorumlar)
    df = pd.DataFrame(comments_data)
    
    # Kufur tespiti sütunu (Geçici olarak veride işaretle)
    df['is_profane'] = df['Yorum'].apply(find_profanity)
    df['is_feedback'] = df['Yorum'].apply(find_suggestion_criticism)

    # 2. Istatistikler 
    total_comments = len(df)
    avg_likes = df['Beğeni'].mean()
    sentiment_counts = df['Sistem Tahmini'].value_counts().to_dict()
    profane_counts = int(df['is_profane'].sum()) # Type cast to native Python int
    
    stats_data = [
        {"Metrik": "Toplam Çekilen Yorum", "Değer": total_comments},
        {"Metrik": "Ortalama Beğeni", "Değer": round(avg_likes, 2)},
        {"Metrik": "Küfürlü/Riskli Yorum Sayısı", "Değer": profane_counts},
        {"Metrik": "Pozitif Yorum", "Değer": sentiment_counts.get('Pozitif', 0)},
        {"Metrik": "Negatif Yorum", "Değer": sentiment_counts.get('Negatif', 0)},
        {"Metrik": "Nötr Yorum", "Değer": sentiment_counts.get('Nötr', 0)},
    ]
    df_stats = pd.DataFrame(stats_data)

    # 3. Kufur Iceren Yorumlar (is_profane filtresi)
    df_profane = df[df['is_profane'] == True].drop(columns=['is_profane', 'is_feedback'])
    
    # 4. En Begilen Yorumlar
    df_top_liked = df.sort_values(by='Beğeni', ascending=False).head(100).drop(columns=['is_profane', 'is_feedback'])
    
    # 5. Oneri_Elestiri_Ozeti
    df_feedback = df[df['is_feedback'] == True].drop(columns=['is_profane', 'is_feedback'])

    # 6. Duygu Dagilimi
    df_sentiment_dist = df['Sistem Tahmini'].value_counts().reset_index()
    df_sentiment_dist.columns = ['Duygu Sınıfı', 'Yorum Sayısı']
    df_sentiment_dist['Yüzde Nitelik (%)'] = round((df_sentiment_dist['Yorum Sayısı'] / total_comments) * 100, 2)

    # Temizleme (Ana tablodan geçici sütunları at)
    df_main = df.drop(columns=['is_profane', 'is_feedback'])

    # Pandas ile çok sekmeli (Multi-sheet) Excel Oluşturma
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df_main.to_excel(writer, sheet_name='Tum Yorumlar', index=False)
        df_stats.to_excel(writer, sheet_name='Istatistikler', index=False)
        
        # Eğer kufur iceren yoksa bos tablo atmasi bile guzel durur
        if len(df_profane) > 0:
            df_profane.to_excel(writer, sheet_name='Kufur Iceren Yorumlar', index=False)
        else:
            pd.DataFrame({"Mesaj": ["Küfür içeren yorum tespit edilmedi."]}).to_excel(writer, sheet_name='Kufur Iceren Yorumlar', index=False)
            
        df_top_liked.to_excel(writer, sheet_name='En Begilen Yorumlar', index=False)
        
        if len(df_feedback) > 0:
            df_feedback.to_excel(writer, sheet_name='Oneri_Elestiri_Ozeti', index=False)
        else:
            pd.DataFrame({"Mesaj": ["Öneri/Eleştiri kelimesi taşıyan yorum bulunamadı."]}).to_excel(writer, sheet_name='Oneri_Elestiri_Ozeti', index=False)
            
        df_sentiment_dist.to_excel(writer, sheet_name='Duygu_Dagilimi', index=False)
    
    return True
