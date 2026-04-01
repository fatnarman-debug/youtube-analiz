#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
YouTube Yorum Analiz Aracı
Tüm özellikleri tek dosyada içerir
"""

import re
import pandas as pd
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import emoji
from collections import Counter
import time
import os
from fpdf import FPDF
import textwrap

# ==================== KONFİGÜRASYON ====================

# Türkçe küfür listesi (Tam kelime eşleşmesi için genişletilmiş ekli liste - set kullanımı hız kazandırır)
PROFANITY_LIST = {
    'amk', 'amına', 'amcık', 'amcik', 'orospu', 'oç', 'oc', 'piç', 'pic', 'piçi', 'piçin', 'piçler',
    'sik', 'siki', 'sikik', 'sikin', 'sikim', 'sikime', 'sikler', 'siktir', 'siktirgit', 
    'sikeyim', 'siktiğim', 'sikiyim', 'sikerim', 'siktim', 'sikerek', 'sikilmiş', 'sikerler',
    'göt', 'götü', 'götün', 'göte', 'götten', 'götüm', 'götüme', 'götüne', 'götveren', 'götlük', 'götler',
    'gerizekalı', 'gerizekali', 'salak', 'aptal', 'embesil', 'mal', 'manyak', 'dangalak',
    'ananı', 'babanı', 'kahpe', 'fahişe', 'şerefsiz', 'namussuz', 'yavşak', 'yavsak', 'pezevenk',
    'aq', 'amq', 'mk', 'sg', 'am', 'amı', 'amın', 'amdan'
}

# Öneri ve eleştiri kalıpları
SUGGESTION_PATTERNS = [
    r'(?:öneri|tavsiye|şöyle yap|daha iyi olur|keşke|bence şu|şunu ekleyin|şu olsa)(?:[^.!?]+)',
    r'(?:should|could|would be better|suggestion|recommend|please add|please make)(?:[^.!?]+)',
    r'(?:umarım|umut|beklenti|dilek)(?:[^.!?]+)'
]

CRITICISM_PATTERNS = [
    r'(?:eleştiri|beğenmedim|kötü|başarısız|hayal kırıklığı|yanlış|eksik|hata)(?:[^.!?]+)',
    r'(?:bad|disappointing|wrong|terrible|not good|worse|missed|error)(?:[^.!?]+)',
    r'(?:neden böyle|niye böyle|olmamış|berbat|rezalet)(?:[^.!?]+)'
]

# ==================== 1. YORUM TOPLAMA ====================

class YouTubeCommentAnalyzer:
    def __init__(self, youtube_api_key):
        self.youtube_api_key = youtube_api_key
        self.youtube = None
        self.video_id = None
        self.video_title = None
        self.comments_df = None
        self.error_log = None
        
    def extract_video_id(self, url_or_id):
        """YouTube URL'sinden video ID'sini çıkarır"""
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
            r'^([a-zA-Z0-9_-]{11})$'
        ]
        for pattern in patterns:
            match = re.search(pattern, url_or_id)
            if match:
                return match.group(1)
        return None
    
    def get_video_details(self):
        """Video başlığı ve detaylarını alır"""
        try:
            request = self.youtube.videos().list(
                part='snippet',
                id=self.video_id
            )
            response = request.execute()
            if response['items']:
                self.video_title = response['items'][0]['snippet']['title']
                return True
        except HttpError as e:
            self.error_log = f"YouTube API Hatası: {e.reason if hasattr(e, 'reason') else str(e)}"
            print(f"Video detayları alınamadı: {self.error_log}")
        except Exception as e:
            self.error_log = f"Beklenmeyen Hata (Video Detay): {str(e)}"
            print(f"Video detayları alınamadı: {self.error_log}")
        return False
    
    def collect_comments(self, max_comments=500):
        """YouTube'dan yorumları toplar"""
        self.youtube = build('youtube', 'v3', developerKey=self.youtube_api_key)
        
        if not self.get_video_details():
            print("Video bulunamadı!")
            return False
        
        comments = []
        next_page_token = None
        
        print(f"Yorumlar toplanıyor: {self.video_title}")
        
        while len(comments) < max_comments:
            try:
                request = self.youtube.commentThreads().list(
                    part='snippet,replies',
                    videoId=self.video_id,
                    maxResults=min(100, max_comments - len(comments)),
                    pageToken=next_page_token,
                    textFormat='plainText'
                )
                response = request.execute()
                
                for item in response['items']:
                    snippet = item['snippet']['topLevelComment']['snippet']
                    comment_data = {
                        'kullanici': snippet['authorDisplayName'],
                        'yorum': self.clean_text(snippet['textDisplay']),
                        'begeni_sayisi': snippet['likeCount'],
                        'tarih': snippet['publishedAt'],
                        'kullanici_kanal_id': snippet.get('authorChannelId', {}).get('value', ''),
                        'yorum_id': item['snippet']['topLevelComment']['id'],
                        'yanit_sayisi': item['snippet']['totalReplyCount']
                    }
                    comments.append(comment_data)
                    
                    # Yanıtları da al (opsiyonel)
                    if 'replies' in item and item['replies']:
                        for reply in item['replies']['comments']:
                            reply_snippet = reply['snippet']
                            comment_data = {
                                'kullanici': reply_snippet['authorDisplayName'],
                                'yorum': self.clean_text(reply_snippet['textDisplay']),
                                'begeni_sayisi': reply_snippet['likeCount'],
                                'tarih': reply_snippet['publishedAt'],
                                'kullanici_kanal_id': reply_snippet.get('authorChannelId', {}).get('value', ''),
                                'yorum_id': reply['id'],
                                'yanit_sayisi': 0
                            }
                            comments.append(comment_data)
                
                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break
                    
                # API kotasını aşmamak için bekle
                time.sleep(0.1)
                
            except HttpError as e:
                if e.resp.status == 403:
                    print("API kotası aşıldı veya yorumlar kapalı.")
                else:
                    print(f"API hatası: {e}")
                break
            except Exception as e:
                print(f"Beklenmeyen hata: {e}")
                break
        
        self.comments_df = pd.DataFrame(comments)
        print(f"Toplam {len(self.comments_df)} yorum toplandı.")
        return True
    
    def clean_text(self, text):
        """Metni temizler"""
        if not text:
            return ""
        # Emojileri temizle (opsiyonel, saklamak istersen kaldır)
        text = emoji.replace_emoji(text, replace='')
        # Fazla boşlukları temizle
        text = re.sub(r'\s+', ' ', text)
        # HTML entity'leri temizle
        text = re.sub(r'&[a-z]+;', '', text)
        return text.strip()
    
    # ==================== 2. DUYGU ANALİZİ ====================
    
    def analyze_sentiment_textblob(self, text):
        """TextBlob ile duygu analizi (Türkçe için sınırlı)"""
        if not text:
            return 'notr'
        try:
            analysis = TextBlob(text)
            polarity = analysis.sentiment.polarity
            if polarity > 0.1:
                return 'olumlu'
            elif polarity < -0.1:
                return 'olumsuz'
            else:
                return 'notr'
        except:
            return 'notr'
    
    def analyze_sentiment_vader(self, text):
        """VADER ile duygu analizi (İngilizce için iyi)"""
        if not text:
            return 'notr'
        try:
            analyzer = SentimentIntensityAnalyzer()
            scores = analyzer.polarity_scores(text)
            if scores['compound'] >= 0.05:
                return 'olumlu'
            elif scores['compound'] <= -0.05:
                return 'olumsuz'
            else:
                return 'notr'
        except:
            return 'notr'
    
    def analyze_sentiment_turkish(self, text):
        """Türkçe kelime tabanlı basit duygu analizi"""
        if not text:
            return 'notr'
        
        text_lower = text.lower()
        
        # Olumlu kelimeler
        positive_words = ['harika', 'mükemmel', 'süper', 'güzel', 'iyi', 'beğendim', 
                         'teşekkür', 'ellerinize sağlık', 'başarılı', 'kaliteli', 
                         'şaşırtıcı', 'hayran', 'tavsiye', 'severek', 'keyifle']
        
        # Olumsuz kelimeler
        negative_words = ['berbat', 'kötü', 'rezalet', 'hayal kırıklığı', 'sıkıcı', 
                         'zaman kaybı', 'anlamadım', 'gereksiz', 'saçma', 'yanlış',
                         'hata', 'eksik', 'beğenmedim', 'bıktım', 'sıkıldım']
        
        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)
        
        if pos_count > neg_count:
            return 'olumlu'
        elif neg_count > pos_count:
            return 'olumsuz'
        else:
            return 'notr'
    
    def detect_profanity(self, text):
        """Küfür tespiti yapar (Kelime bazlı)"""
        if not text:
            return False, []
        
        # Türkçe küçük harfe çevirme (Örn: SIKINTI -> sıkıntı - I harfi dönüşümü önemli)
        text_lower = text.replace('I', 'ı').replace('İ', 'i').lower()
        
        # Sadece alfabetik karakterleri alarak kelimeleri ayır
        words = re.findall(r'[a-zçğıöşü]+', text_lower)
        found_words = set()
        
        for word in words:
            # Sadece tam kelime eşleşmesi yap (böylece göt => götürmek eşleşmez)
            if word in PROFANITY_LIST:
                found_words.add(word)
        
        # Yıldızlı ve noktalı küfürleri kontrol et (Örnek: a.m.k, s*k, o.ç)
        # \b kelime sınırıdır, kelime içinde geçmesini engeller
        starred_pattern = r'\b(s[\*_\-\.\s]+[kq]|a[\*_\-\.\s]+m[\*_\-\.\s]+[kq]|o[\*_\-\.\s]+[çc]|p[\*_\-\.\s]+[çc])\b'
        if re.search(starred_pattern, text_lower):
            found_words.add('(sansürlü küfür)')
        
        return len(found_words) > 0, list(found_words)
    
    # ==================== 3. ÖNERİ VE ELEŞTİRİ ÇIKARIMI ====================
    
    def extract_suggestions(self, text):
        """Yorumlardan öneri cümlelerini çıkarır"""
        if not text:
            return []
        
        suggestions = []
        for pattern in SUGGESTION_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            suggestions.extend(matches)
        
        # İpucu bazlı öneri tespiti
        hint_words = ['öner', 'tavsiye', 'şöyle yap', 'daha iyi', 'keşke', 'bence', 'eklenmeli']
        if any(word in text.lower() for word in hint_words):
            if len(text) < 200:  # Kısa öneri cümleleri
                suggestions.append(text)
        
        return suggestions[:3]  # En fazla 3 öneri
    
    def extract_criticisms(self, text):
        """Yorumlardan eleştiri cümlelerini çıkarır"""
        if not text:
            return []
        
        criticisms = []
        for pattern in CRITICISM_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            criticisms.extend(matches)
        
        # İpucu bazlı eleştiri tespiti
        hint_words = ['eleştiri', 'beğenmedim', 'kötü', 'yanlış', 'eksik', 'hata']
        if any(word in text.lower() for word in hint_words):
            if len(text) < 200:
                criticisms.append(text)
        
        return criticisms[:3]  # En fazla 3 eleştiri
    
    def detect_question(self, text):
        """Yorumun soru içerip içermediğini tespit eder"""
        if not text:
            return False
            
        text_lower = text.replace('I', 'ı').replace('İ', 'i').lower()
        if '?' in text:
            return True
            
        words = re.findall(r'[a-zçğıöşü]+', text_lower)
        question_particles = {'mi', 'mı', 'mu', 'mü', 'misin', 'mısın', 'musun', 'müsün', 'miyim', 'mıyım', 'muyum', 'müyüm', 'miyiz', 'mıyız', 'muyuz', 'müyüz'}
        if any(w in question_particles for w in words):
            return True
            
        return False
    
    # ==================== 4. ANALİZ VE RAPORLAMA ====================
    
    def run_full_analysis(self, method='turkish'):
        """Tüm analizleri çalıştırır"""
        if self.comments_df is None or self.comments_df.empty:
            print("Önce yorumları toplayın!")
            return False
        
        print("Analiz başlıyor...")
        
        # Duygu analizi
        if method == 'textblob':
            self.comments_df['duygu'] = self.comments_df['yorum'].apply(self.analyze_sentiment_textblob)
        elif method == 'vader':
            self.comments_df['duygu'] = self.comments_df['yorum'].apply(self.analyze_sentiment_vader)
        else:
            self.comments_df['duygu'] = self.comments_df['yorum'].apply(self.analyze_sentiment_turkish)
        
        # Küfür tespiti
        self.comments_df['kufur_iceriyor'], self.comments_df['kufur_kelimeleri'] = zip(*self.comments_df['yorum'].apply(self.detect_profanity))
        
        # Öneri ve eleştiri çıkarımı
        self.comments_df['oneri'] = self.comments_df['yorum'].apply(self.extract_suggestions)
        self.comments_df['elestiri'] = self.comments_df['yorum'].apply(self.extract_criticisms)
        
        # Soru tespiti
        self.comments_df['soru_iceriyor'] = self.comments_df['yorum'].apply(self.detect_question)
        
        # Zaman damgası ekle
        self.comments_df['analiz_tarihi'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print("Analiz tamamlandı!")
        return True
    
    def get_statistics(self):
        """İstatistiksel özet döndürür"""
        if self.comments_df is None or self.comments_df.empty:
            return None
        
        total = len(self.comments_df)
        sentiment_counts = self.comments_df['duygu'].value_counts()
        
        stats = {
            'toplam_yorum': total,
            'olumlu_sayi': sentiment_counts.get('olumlu', 0),
            'olumsuz_sayi': sentiment_counts.get('olumsuz', 0),
            'notr_sayi': sentiment_counts.get('notr', 0),
            'olumlu_yuzde': (sentiment_counts.get('olumlu', 0) / total * 100) if total > 0 else 0,
            'olumsuz_yuzde': (sentiment_counts.get('olumsuz', 0) / total * 100) if total > 0 else 0,
            'notr_yuzde': (sentiment_counts.get('notr', 0) / total * 100) if total > 0 else 0,
            'kufur_sayi': self.comments_df['kufur_iceriyor'].sum(),
            'kufur_yuzde': (self.comments_df['kufur_iceriyor'].sum() / total * 100) if total > 0 else 0,
            'soru_sayi': self.comments_df['soru_iceriyor'].sum() if 'soru_iceriyor' in self.comments_df.columns else 0,
            'soru_yuzde': (self.comments_df['soru_iceriyor'].sum() / total * 100) if total > 0 and 'soru_iceriyor' in self.comments_df.columns else 0,
            'ortalama_begeni': self.comments_df['begeni_sayisi'].mean() if total > 0 else 0,
            'en_cok_begenilen': self.comments_df.nlargest(1, 'begeni_sayisi')[['kullanici', 'yorum', 'begeni_sayisi']].iloc[0].to_dict() if total > 0 else {}
        }
        
        return stats
    
    def get_profanity_users(self):
        """Küfür içeren yorumları ve kullanıcıları listeler"""
        profanity_df = self.comments_df[self.comments_df['kufur_iceriyor'] == True]
        if profanity_df.empty:
            return []
        
        return profanity_df[['kullanici', 'yorum', 'kufur_kelimeleri', 'begeni_sayisi']].to_dict('records')
    
    def get_top_suggestions(self, limit=10):
        """En iyi önerileri listeler"""
        all_suggestions = []
        for suggestions in self.comments_df['oneri'].dropna():
            if isinstance(suggestions, list):
                all_suggestions.extend(suggestions)
        
        # Benzersiz önerileri say
        suggestion_counts = Counter(all_suggestions)
        return suggestion_counts.most_common(limit)
    
    def get_top_criticisms(self, limit=10):
        """En iyi eleştirileri listeler"""
        all_criticisms = []
        for criticisms in self.comments_df['elestiri'].dropna():
            if isinstance(criticisms, list):
                all_criticisms.extend(criticisms)
        
        criticism_counts = Counter(all_criticisms)
        return criticism_counts.most_common(limit)
    
    def generate_summary_text(self):
        """Anlamlı özet metin oluşturur"""
        stats = self.get_statistics()
        if not stats:
            return "Yeterli veri yok."
        
        summary = []
        summary.append(f"\n{'='*60}")
        summary.append(f"📊 YOUTUBE YORUM ANALİZ RAPORU")
        summary.append(f"{'='*60}")
        summary.append(f"🎬 Video: {self.video_title}")
        summary.append(f"🆔 Video ID: {self.video_id}")
        summary.append(f"📅 Analiz Tarihi: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        summary.append(f"")
        summary.append(f"📈 GENEL İSTATİSTİKLER")
        summary.append(f"{'-'*40}")
        summary.append(f"📝 Toplam Yorum: {stats['toplam_yorum']}")
        summary.append(f"👍 Toplam Beğeni: {int(self.comments_df['begeni_sayisi'].sum())}")
        summary.append(f"⭐ Ortalama Beğeni/Yorum: {stats['ortalama_begeni']:.1f}")
        summary.append(f"")
        summary.append(f"😊 DUYGU ANALİZİ")
        summary.append(f"{'-'*40}")
        summary.append(f"😃 Olumlu: {stats['olumlu_sayi']} yorum ({stats['olumlu_yuzde']:.1f}%)")
        summary.append(f"😞 Olumsuz: {stats['olumsuz_sayi']} yorum ({stats['olumsuz_yuzde']:.1f}%)")
        summary.append(f"😐 Nötr: {stats['notr_sayi']} yorum ({stats['notr_yuzde']:.1f}%)")
        summary.append(f"")
        
        # Duygu grafiği (basit ASCII)
        pos_bar = int(stats['olumlu_yuzde'] / 2)
        neg_bar = int(stats['olumsuz_yuzde'] / 2)
        neu_bar = int(stats['notr_yuzde'] / 2)
        summary.append(f"Grafik: [{'😃' * pos_bar}{'😐' * neu_bar}{'😞' * neg_bar}]")
        summary.append(f"")
        
        summary.append(f"⚠️ KÜFÜR ANALİZİ")
        summary.append(f"{'-'*40}")
        summary.append(f"🚫 Küfür İçeren Yorum: {stats['kufur_sayi']} ({stats['kufur_yuzde']:.1f}%)")
        
        profanity_users = self.get_profanity_users()
        if profanity_users:
            summary.append(f"👤 Küfür Eden Kullanıcılar ({len(profanity_users)} kişi):")
            for i, user in enumerate(profanity_users[:10], 1):
                summary.append(f"   {i}. {user['kullanici']} - \"{user['yorum'][:50]}...\"")
            if len(profanity_users) > 10:
                summary.append(f"   ... ve {len(profanity_users)-10} kişi daha")
        else:
            summary.append(f"✅ Küfür tespit edilmedi!")
        
        summary.append(f"")
        summary.append(f"💡 ÖNE ÇIKAN ÖNERİLER")
        summary.append(f"{'-'*40}")
        suggestions = self.get_top_suggestions(8)
        if suggestions:
            for i, (suggestion, count) in enumerate(suggestions, 1):
                summary.append(f"{i}. {suggestion[:100]} ( {count} kez )")
        else:
            summary.append(f"Belirgin bir öneri tespit edilmedi.")
        
        summary.append(f"")
        summary.append(f"🔧 ÖNE ÇIKAN ELEŞTİRİLER")
        summary.append(f"{'-'*40}")
        criticisms = self.get_top_criticisms(8)
        if criticisms:
            for i, (criticism, count) in enumerate(criticisms, 1):
                summary.append(f"{i}. {criticism[:100]} ( {count} kez )")
        else:
            summary.append(f"Belirgin bir eleştiri tespit edilmedi.")
        
        if stats['toplam_yorum'] > 0:
            summary.append(f"")
            summary.append(f"🏆 EN BEĞENİLEN YORUM")
            summary.append(f"{'-'*40}")
            top_comment = self.comments_df.nlargest(1, 'begeni_sayisi').iloc[0]
            summary.append(f"👤 {top_comment['kullanici']} ({top_comment['begeni_sayisi']} beğeni)")
            summary.append(f"💬 {top_comment['yorum'][:150]}")
        
        summary.append(f"")
        summary.append(f"{'='*60}")
        summary.append(f"📁 Detaylı veriler için Excel dosyasını inceleyin.")
        summary.append(f"{'='*60}")
        
        return "\n".join(summary)
    
    def create_excel_report(self, output_path=None):
        """Excel raporu oluşturur"""
        if self.comments_df is None or self.comments_df.empty:
            print("Yorum verisi yok!")
            return None
        
        if output_path is None:
            output_path = f"youtube_analiz_{self.video_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Sayfa 1: Tüm Yorumlar
            df_display = self.comments_df.copy()
            df_display['oneri'] = df_display['oneri'].apply(lambda x: ', '.join(x) if isinstance(x, list) else '')
            df_display['elestiri'] = df_display['elestiri'].apply(lambda x: ', '.join(x) if isinstance(x, list) else '')
            df_display['kufur_kelimeleri'] = df_display['kufur_kelimeleri'].apply(lambda x: ', '.join(x) if isinstance(x, list) else '')
            df_display.to_excel(writer, sheet_name='Tum Yorumlar', index=False)
            
            # Sayfa 2: İstatistikler
            stats = self.get_statistics()
            stats_df = pd.DataFrame([
                ['Toplam Yorum', stats['toplam_yorum'], '100%'],
                ['Olumlu Yorum', stats['olumlu_sayi'], f"{stats['olumlu_yuzde']:.1f}%"],
                ['Olumsuz Yorum', stats['olumsuz_sayi'], f"{stats['olumsuz_yuzde']:.1f}%"],
                ['Nötr Yorum', stats['notr_sayi'], f"{stats['notr_yuzde']:.1f}%"],
                ['Soru İçeren', stats['soru_sayi'], f"{stats['soru_yuzde']:.1f}%"],
                ['Küfür İçeren', stats['kufur_sayi'], f"{stats['kufur_yuzde']:.1f}%"],
                ['Ortalama Beğeni', f"{stats['ortalama_begeni']:.1f}", '-'],
                ['Toplam Beğeni', int(self.comments_df['begeni_sayisi'].sum()), '-']
            ], columns=['Metrik', 'Sayı', 'Yüzde'])
            stats_df.to_excel(writer, sheet_name='Istatistikler', index=False)
            
            # Sayfa 3: Gelen Sorular
            soru_df = self.comments_df[self.comments_df['soru_iceriyor'] == True]
            if not soru_df.empty:
                soru_df[['kullanici', 'yorum', 'begeni_sayisi', 'tarih']].to_excel(
                    writer, sheet_name='Gelen Sorular', index=False
                )
            
            # Sayfa 4: Küfür İçeren Yorumlar
            profanity_df = self.comments_df[self.comments_df['kufur_iceriyor'] == True]
            if not profanity_df.empty:
                profanity_df[['kullanici', 'yorum', 'kufur_kelimeleri', 'begeni_sayisi']].to_excel(
                    writer, sheet_name='Kufur Iceren Yorumlar', index=False
                )
            
            # Sayfa 4: En Beğenilen Yorumlar
            top_comments = self.comments_df.nlargest(min(50, len(self.comments_df)), 'begeni_sayisi')
            top_comments[['kullanici', 'yorum', 'begeni_sayisi', 'duygu']].to_excel(
                writer, sheet_name='En Begilen Yorumlar', index=False
            )
            
            # Sayfa 5: Öneri ve Eleştiri Özeti
            suggestions = self.get_top_suggestions(20)
            criticisms = self.get_top_criticisms(20)
            
            max_len = max(len(suggestions), len(criticisms))
            summary_data = []
            for i in range(max_len):
                suggestion_text = suggestions[i][0] if i < len(suggestions) else ''
                suggestion_count = suggestions[i][1] if i < len(suggestions) else ''
                criticism_text = criticisms[i][0] if i < len(criticisms) else ''
                criticism_count = criticisms[i][1] if i < len(criticisms) else ''
                summary_data.append([suggestion_text, suggestion_count, criticism_text, criticism_count])
            
            summary_df = pd.DataFrame(summary_data, columns=['Öneri', 'Tekrar Sayısı', 'Eleştiri', 'Tekrar Sayısı'])
            summary_df.to_excel(writer, sheet_name='Oneri_Elestiri_Ozeti', index=False)
            
            # Sayfa 6: Duygu Dağılımı (Pivot)
            sentiment_pivot = self.comments_df.groupby(['duygu']).agg({
                'yorum': 'count',
                'begeni_sayisi': 'sum'
            }).rename(columns={'yorum': 'yorum_sayisi', 'begeni_sayisi': 'toplam_begeni'})
            sentiment_pivot.to_excel(writer, sheet_name='Duygu_Dagilimi')
        
        print(f"✅ Excel raporu oluşturuldu: {output_path}")
        return output_path

    def create_pdf_report(self, output_path=None):
        """FPDF kullanarak PDF raporu oluşturur"""
        if self.comments_df is None or self.comments_df.empty:
            return None
        
        if output_path is None:
            output_path = f"youtube_analiz_{self.video_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        stats = self.get_statistics()
        
        # PDF Ayarları
        pdf = FPDF()
        pdf.add_page()
        
        # Font Ayarı (Regular, Bold, Italic, Bold-Italic)
        # Linux/Docker DejaVu font yolları
        font_base = "/usr/share/fonts/truetype/dejavu/DejaVuSans"
        font_variants = [
            ("", f"{font_base}.ttf"),
            ("B", f"{font_base}-Bold.ttf"),
            ("I", f"{font_base}-Oblique.ttf"),
            ("BI", f"{font_base}-BoldOblique.ttf"),
        ]
        
        main_font_loaded = False
        for style, fpath in font_variants:
            if os.path.exists(fpath):
                try:
                    pdf.add_font("UnicodeFont", style, fpath)
                    if style == "": main_font_loaded = True
                except:
                    pass
        
        # Mac Fallback (Arial Unicode)
        if not main_font_loaded:
            mac_font = "/Library/Fonts/Arial Unicode.ttf"
            if os.path.exists(mac_font):
                try:
                    pdf.add_font("UnicodeFont", "", mac_font)
                    pdf.add_font("UnicodeFont", "B", mac_font)
                    pdf.add_font("UnicodeFont", "I", mac_font)
                    pdf.add_font("UnicodeFont", "BI", mac_font)
                    main_font_loaded = True
                except:
                    pass

        if main_font_loaded:
            pdf.set_font("UnicodeFont", size=12)
        else:
            # Kritik: Eğer Unicode font yüklenemediyse bile hata vermesin, 
            # standart Helvetica'ya dönüp devam etsin (Türkçe karakterler bozulabilir ama uygulama çökmez).
            pdf.set_font("Helvetica", size=11)

        # Başlık Bölümü
        pdf.set_font(style='B', size=20)
        pdf.cell(200, 10, txt="VidInsight Analiz Raporu", ln=True, align='C')
        pdf.ln(5)
        
        # Video Bilgileri
        pdf.set_font(size=10)
        pdf.set_text_color(100)
        pdf.cell(200, 10, txt=f"Rapor Tarihi: {datetime.now().strftime('%d.%m.%Y %H:%M')}", ln=True, align='C')
        pdf.ln(10)
        
        pdf.set_text_color(0)
        pdf.set_font(style='B', size=14)
        pdf.cell(200, 10, txt=f"Video Bilgileri", ln=True)
        pdf.set_font(size=12)
        pdf.multi_cell(0, 10, txt=f"Başlık: {self.video_title}")
        pdf.cell(200, 10, txt=f"ID: {self.video_id}", ln=True)
        pdf.ln(5)
        
        # İstatistikler
        pdf.set_font(style='B', size=14)
        pdf.cell(200, 10, txt="Genel İstatistikler", ln=True)
        pdf.set_font(size=11)
        
        # Tablo benzeri yapı
        stats_list = [
            ("Toplam Yorum", str(stats['toplam_yorum'])),
            ("Toplam Beğeni", str(int(self.comments_df['begeni_sayisi'].sum()))),
            ("Olumlu Yorum Oranı", f"%{stats['olumlu_yuzde']:.1f}"),
            ("Olumsuz Yorum Oranı", f"%{stats['olumsuz_yuzde']:.1f}"),
            ("Küfür İçeren Yorum", str(stats['kufur_sayi'])),
            ("Soru İçeren Yorum", str(stats['soru_sayi']))
        ]
        
        for label, val in stats_list:
            pdf.cell(60, 10, txt=label, border=1)
            pdf.cell(40, 10, txt=val, border=1, ln=True)
        
        pdf.ln(10)
        
        # Duygu Analizi Özeti
        pdf.set_font(style='B', size=14)
        pdf.cell(200, 10, txt="Duygu Analizi", ln=True)
        pdf.set_font(size=11)
        
        sentiment_txt = f"Video altındaki yorumların %{stats['olumlu_yuzde']:.1f}'i olumlu, %{stats['olumsuz_yuzde']:.1f}'i olumsuz ve %{stats['notr_yuzde']:.1f}'i nötr olarak belirlenmiştir."
        pdf.multi_cell(0, 8, txt=sentiment_txt)
        pdf.ln(5)
        
        # En Beğenilen Yorum
        pdf.set_font(style='B', size=14)
        pdf.cell(200, 10, txt="En Beğenilen Yorum", ln=True)
        pdf.set_font(style='I', size=11)
        top_comment = stats['en_cok_begenilen']
        top_txt = f"\"{top_comment['yorum']}\" - {top_comment['kullanici']} ({top_comment['begeni_sayisi']} Beğeni)"
        pdf.multi_cell(0, 8, txt=top_txt)
        pdf.ln(5)

        # Öneriler (İlk 5)
        suggestions = self.get_top_suggestions(5)
        if suggestions:
            pdf.set_font(style='B', size=14)
            pdf.cell(200, 10, txt="Öne Çıkan Öneriler", ln=True)
            pdf.set_font(size=10)
            for i, (sug, count) in enumerate(suggestions, 1):
                pdf.multi_cell(0, 8, txt=f"{i}. {sug[:200]} ({count} kez)")
            pdf.ln(5)

        # Eleştiriler (İlk 5)
        criticisms = self.get_top_criticisms(5)
        if criticisms:
            pdf.set_font(style='B', size=14)
            pdf.cell(200, 10, txt="Öne Çıkan Eleştiriler", ln=True)
            pdf.set_font(size=10)
            for i, (crit, count) in enumerate(criticisms, 1):
                pdf.multi_cell(0, 8, txt=f"{i}. {crit[:200]} ({count} kez)")
            pdf.ln(5)
            
        # Kaydet
        pdf.output(output_path)
        print(f"✅ PDF raporu oluşturuldu: {output_path}")
        return output_path
    
    def generate_gemini_prompt(self):
        """Gemini API için hazır prompt oluşturur"""
        stats = self.get_statistics()
        if not stats:
            return "Veri yok"
            
        positive_comments = self.comments_df[self.comments_df['duygu'] == 'olumlu']['yorum'].head(20).tolist()
        negative_comments = self.comments_df[self.comments_df['duygu'] == 'olumsuz']['yorum'].head(20).tolist()
        suggestions = self.get_top_suggestions(10)
        criticisms = self.get_top_criticisms(10)
        
        prompt = f"""
# YouTube Yorum Analizi İçin Gemini Değerlendirmesi

## Video Bilgileri
- Başlık: {self.video_title}
- Toplam Yorum: {stats['toplam_yorum']}
- Olumlu Yorum: {stats['olumlu_sayi']} ({stats['olumlu_yuzde']:.1f}%)
- Olumsuz Yorum: {stats['olumsuz_sayi']} ({stats['olumsuz_yuzde']:.1f}%)
- Nötr Yorum: {stats['notr_sayi']} ({stats['notr_yuzde']:.1f}%)

## Öne Çıkan Öneriler
{chr(10).join([f'- {s[0]}' for s in suggestions[:10]])}

## Öne Çıkan Eleştiriler
{chr(10).join([f'- {c[0]}' for c in criticisms[:10]])}

## Olumlu Yorum Örnekleri
{chr(10).join([f'"{c}"' for c in positive_comments[:5]])}

## Olumsuz Yorum Örnekleri
{chr(10).join([f'"{c}"' for c in negative_comments[:5]])}

## İstenen Analiz
Lütfen aşağıdaki başlıklarda detaylı bir analiz sun:

1. GENEL DEĞERLENDİRME: Video içeriğinin izleyici tarafından nasıl karşılandığı
2. GÜÇLÜ YANLAR: İzleyicilerin en çok beğendiği noktalar
3. ZAYIF YANLAR: İzleyicilerin eleştirdiği noktalar
4. SOMUT ÖNERİLER: İçerik üreticisine verilebilecek aksiyon önerileri
5. SONUÇ: Kısa bir özet ve tavsiye

Analizi Türkçe yap, profesyonel ve yapıcı bir dil kullan.
"""
        return prompt


# ==================== 5. ANA ÇALIŞTIRMA FONKSİYONU ====================

def analyze_youtube_video(youtube_url, youtube_api_key, max_comments=500, sentiment_method='turkish'):
    """
    Ana analiz fonksiyonu - YouTube videosunu komple analiz eder
    
    Parametreler:
    - youtube_url: YouTube video URL'si veya ID'si
    - youtube_api_key: YouTube Data API v3 anahtarı
    - max_comments: Maksimum yorum sayısı (varsayılan: 500)
    - sentiment_method: Duygu analizi yöntemi ('turkish', 'textblob', 'vader')
    
    Dönüş:
    - (summary_text, excel_path) tuple'ı
    """
    analyzer = YouTubeCommentAnalyzer(youtube_api_key)
    
    # Video ID'yi çıkar
    video_id = analyzer.extract_video_id(youtube_url)
    if not video_id:
        print("❌ Geçersiz YouTube URL'si veya ID'si!")
        return None, None, None
    
    analyzer.video_id = video_id
    
    # Yorumları topla
    print("🚀 YouTube yorumları toplanıyor...")
    success = analyzer.collect_comments(max_comments)
    if not success or analyzer.comments_df is None or analyzer.comments_df.empty:
        print("❌ Yorumlar toplanamadı! (Video yorumlara kapalı olabilir)")
        return None, None, None
    
    # Analiz yap
    print("🔍 Duygu analizi ve küfür tespiti yapılıyor...")
    analyzer.run_full_analysis(method=sentiment_method)
    
    # Özet metin oluştur
    summary_text = analyzer.generate_summary_text()
    print(summary_text)
    
    # Excel raporu oluştur
    excel_path = analyzer.create_excel_report()
    
    # Gemini prompt'u da göster (isteğe bağlı)
    gemini_prompt = analyzer.generate_gemini_prompt()
    
    # Gemini prompt'u ayrı bir dosyaya kaydet
    prompt_path = f"gemini_prompt_{analyzer.video_id}.txt"
    with open(prompt_path, 'w', encoding='utf-8') as f:
        f.write(gemini_prompt)
    print(f"📝 Gemini prompt'u kaydedildi: {prompt_path}")
    
    return summary_text, excel_path, prompt_path


# ==================== 6. KULLANIM ÖRNEĞİ ====================

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║     YouTube Yorum Analiz Aracı - Tam Sürüm              ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    # Kullanıcıdan bilgileri al
    youtube_url = input("YouTube video URL'si veya ID'si: ").strip()
    api_key = input("YouTube Data API v3 anahtarı: ").strip()
    
    try:
        max_comments = int(input("Analiz edilecek maksimum yorum sayısı (varsayılan: 500): ") or "500")
    except:
        max_comments = 500
    
    print("\nDuygu analizi yöntemi seçin:")
    print("1. Türkçe kelime tabanlı (önerilen)")
    print("2. TextBlob (İngilizce için)")
    print("3. VADER (İngilizce sosyal medya için)")
    
    method_choice = input("Seçiminiz (1-3): ").strip()
    method_map = {'1': 'turkish', '2': 'textblob', '3': 'vader'}
    sentiment_method = method_map.get(method_choice, 'turkish')
    
    print("\n" + "="*60)
    print("Analiz başlatılıyor... Bu işlem birkaç dakika sürebilir.")
    print("="*60 + "\n")
    
    # Analizi çalıştır
    summary, excel_path, prompt_path = analyze_youtube_video(
        youtube_url=youtube_url,
        youtube_api_key=api_key,
        max_comments=max_comments,
        sentiment_method=sentiment_method
    )
    
    if summary:
        print("\n" + "="*60)
        print("İşlem başarıyla tamamlandı!")
        if excel_path:
            print(f"Excel Raporu: {excel_path}")
        if prompt_path:
            print(f"Gemini Prompt: {prompt_path}")
        print("="*60 + "\n")
