#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
YouTube Yorum Özetleyici - Tek Dosya
Verilen yorumları analiz eder ve kısa özet çıkarır
"""

import re
from collections import Counter
from datetime import datetime

# ==================== KONFİGÜRASYON ====================

# Küfür listesi (Tam kelimeler ve yaygın ekleri ile genişletilmiş)
PROFANITY_LIST = {
    'amk', 'amına', 'amcık', 'orospu', 'oç', 'piç', 'sik', 'siki', 'sikik',
    'göt', 'götü', 'götün', 'göte', 'götten', 'götüm', 'götlük', 'götler', 'götüne',
    'kahpe', 'şerefsiz', 'namussuz', 'yavşak', 'pezevenk', 'aq', 'mk', 'amq'
}

# Olumlu kelimeler
POSITIVE_WORDS = [
    'teşekkür', 'sağlık', 'emeğinize', 'rica ederim', 'çok iyi', 
    'başarılı', 'güzel', 'harika', 'mükemmel', 'faydalı', 'bilgilendirici',
    'eyvallah', 'ağzına sağlık', 'elinize sağlık'
]

# Olumsuz kelimeler
NEGATIVE_WORDS = [
    'maalesef', 'kötü', 'sıkıntı', 'zor', 'problem', 'hata', 'bekleme',
    'gecikme', 'red', 'üzgün', 'malesef', 'beceriksiz', 'patladım'
]

# ==================== YORUM VERİSİ ====================

yorumlar = [
    "Hocam dil şartı çıkacak peki mecbur SFI belgesi mi lazım okul bitirmemizde şart mı yoksa sadece sınav mı",
    "Sınavı başarmak şart",
    "Yani kısaca peygamber gibi biri olmak lazım ölüm var yahu İsveçli olsan ne olur vatandaş olunca cennete mi gidecez",
    "Allah Azze ve Celle şöyle buyuruyor: أَلَمْ تَرَ إِلَى الَّذِينَ يَزْعُمُونَ أَنَّهُمْ آمَنُوا بِمَآ أُنْزِلَ إِلَيْكَ وَمَا أُنْزِلَ مِنْ قَبْلِكَ يُرِيدُونَ أَنْ يَتَحَاكَمُوا إِلَى الطَّاغُوتِ وَقَدْ أُمِرُوا أَنْ يَكْفُرُوا بِهِ وَيُرِيدُ الشَّيْطَانُ أَنْ يُضِلَّهُمْ ضَلاَلاً بَعِيدًا",
    "İsveç vatandaşlığı ödüldür dediği yerde patladım",
    "Resmen çocuklarımı uyuşturucudan çetelerden nasıl koruyabilirim diye yemin ederim gözüme uyku girmiyor.",
    "Bu kadar beceriksiz iş bilmez bir devlet ve devlet personeli daha görmedim.",
    "Sorumluluğu ailelere bırakmak yerine senin çocuğunu senin sorumluluğundan alıp özgür birey özgür insan özgür vatandaş saçmalığını çocuklarımızın beynine empoze ediyorlar.",
    "Aile birleşimi vizesine başvurdum süre olarak ne kadar bekleyeceğiz lütfen sorumu cevaplar mısınız?",
    "Biz 6 aydır bekliyoruz sonuç gelmedi malesef",
    "@Ronin4b bilemiyorum umarım bir sorun yaşanmaz tanıdığım biri 6 ay içinde gitti sanırım şans",
    "Vatandaşlık için SFI'ı bitirmenin bir faydası kalmadı diye anlıyorum. Farklı bir sınav talep edecekler diye yorumluyorum. Sizin fikriniz nedir? Teşekkürler",
    "Evet",
    "Hocam kalıcı oturum koşulu hala 4 yıl mı peki?",
    "@eserinanarslan 5 yıl",
    "Kalıcı oturum kuralları aynı şimdilik",
    "Hocam sambo olarak geldim eşim ve burada evlenmeyi düşünüyoruz bu geçiş yasasına yansır mı",
    "Oturumu bu yol ile aldıysa evet",
    "Sizi dinledikten sonra raporu kontrol ettim. Sayfa 35, 11.paragraf 4. Madde c bendi, evli veya sambo olan için 7 yıl yazıyor. Siz 5 yıl dediniz.",
    "İsveç'te 7 yıl yaşamış olacak ama Partneriyle en az 5 yıl birlikte olacak dediğim beş bu...",
    "Hocam spårbyte hakkında bir açıklama yapar mısınız son durum olarak teşekkür ederim",
    "Videosunu yaptım kanalımda var",
    "Hocam yabancılar İsveç vatandaşı olmasın diye ne yapabiliyorlarsa yapmışlar bunun özeti bu.",
    "Hocam peki onları dava edersek konuyu mahkemeye taşırsak bize bir yararı olur mu",
    "Mahkemeler nasıl değerlendirir bilemem! Denemeden bilemeyiz",
    "Merhaba ben toplamda 3 yıl İsveç'te çalıştım legal bir şekilde ve çalışma iznim uzatılmadı, vergi iadem ve emekliliğimle alakalı ne yapabilirim",
    "Zamanı gelince başvuru yapabilirsin",
    "Büyük ihtimalle birçok insan mahkemeye götürecek bu kararı. Teşekkürler Ömer hocam",
    "hocam evlilik üzeri geldim 3.5 yıldır burdayım 2 yılımı doldurup 2 yıllık daha uzatma aldım ben ne zaman permanente başvurabilirim",
    "Toplam 4 seneyi bitirip sınırsız oturmaya başvurabilirsin",
    "Ağzına sağlık sevgili öğretmenim",
    "Teşekkürler",
    "Teşekkür ederim Ömer hocam Emeğinize sağlık",
    "Rica ederim",
    "Hocam 6 Haziran'da mecliste değişir mi bu vatandaşlık tahminin ne yönde",
    "Komisyonda değişir mi bilemem ama ümidim o yönde",
    "Abi ben evlilik üzeri geldim 2 sene sonra ayrılıp iş üzerine çevirdim, bu durumda 5 sene mi yoksa 8 sene mi geçerli?",
    "Trafik cezası vatandaşlık başvuru sonucu etkiler mi?",
    "Dürüst yaşam sınırları ne yasalaşınca göreceğiz",
    "@sinankaya8906 evet etkiliyor bizim bir arkadaş ehliyet süresi bitmişti ve araba kullandı polis yakaladı ceza verdi ve başvurusu da içerisinde red geldi"
]

# ==================== ANALİZ FONKSİYONLARI ====================

def analiz_et(yorum_metni):
    """Tek bir yorumu analiz eder"""
    # Türkçe I/i dönüşümleri sorun yaratmasın
    metin_duzeltilmis = yorum_metni.replace('I', 'ı').replace('İ', 'i').lower()
    
    # Duygu analizi
    olumlu_puan = sum(1 for kelime in POSITIVE_WORDS if kelime.lower() in metin_duzeltilmis)
    olumsuz_puan = sum(1 for kelime in NEGATIVE_WORDS if kelime.lower() in metin_duzeltilmis)
    
    if olumlu_puan > olumsuz_puan:
        duygu = "olumlu"
    elif olumsuz_puan > olumlu_puan:
        duygu = "olumsuz"
    else:
        duygu = "notr"
    
    # Küfür kontrolü (Tam kelime eşleşmesi - substring hatasını önlemek için)
    words = re.findall(r'[a-zçğıöşü]+', metin_duzeltilmis)
    kufur_kelimeler = list({w for w in words if w in PROFANITY_LIST})
    kufur = len(kufur_kelimeler) > 0
    
    # Soru mu?
    soru = '?' in yorum_metni or 'mi ' in metin_duzeltilmis or 'mı ' in metin_duzeltilmis or 'mu ' in metin_duzeltilmis or 'mü ' in metin_duzeltilmis
    
    # Öneri/eleştiri tespiti
    oneri = any(kelime in metin_duzeltilmis for kelime in ['öner', 'tavsiye', 'nasıl', 'ne zaman', 'kaç yıl', 'süre'])
    elestiri = any(kelime in metin_duzeltilmis for kelime in ['maalesef', 'kötü', 'sıkıntı', 'zor', 'beceriksiz', 'patladım'])
    
    return {
        'duygu': duygu,
        'kufur': kufur,
        'kufur_kelimeler': kufur_kelimeler,
        'soru': soru,
        'oneri': oneri,
        'elestiri': elestiri,
        'uzunluk': len(yorum_metni)
    }

def ozet_cikar(yorum_listesi):
    """Tüm yorumları analiz edip özet çıkarır"""
    
    sonuclar = [analiz_et(y) for y in yorum_listesi]
    
    # İstatistikler
    toplam = len(yorum_listesi)
    olumlu = sum(1 for s in sonuclar if s['duygu'] == 'olumlu')
    olumsuz = sum(1 for s in sonuclar if s['duygu'] == 'olumsuz')
    notr = sum(1 for s in sonuclar if s['duygu'] == 'notr')
    kufur_var = sum(1 for s in sonuclar if s['kufur'])
    sorular = sum(1 for s in sonuclar if s['soru'])
    oneriler = sum(1 for s in sonuclar if s['oneri'])
    elestiriler = sum(1 for s in sonuclar if s['elestiri'])
    
    # En çok geçen kelimeler
    tum_metin = ' '.join(yorum_listesi).lower()
    kelimeler = re.findall(r'\b[a-zçğıöşü]{4,}\b', tum_metin)
    stopwords = {'gibi', 'için', 'sonra', 'nasıl', 'zaman', 'hocam', 'olarak', 'ediyor', 'var', 'ise', 'bana', 'sana', 'bize', 'size'}
    kelimeler = [k for k in kelimeler if k not in stopwords]
    en_cok_kelimeler = Counter(kelimeler).most_common(10)
    
    # Konuları tespit et
    konular = []
    if any('vatandaşlık' in y.lower() for y in yorum_listesi):
        konular.append("🏛️ Vatandaşlık başvuruları")
    if any('oturum' in y.lower() or 'permanente' in y.lower() for y in yorum_listesi):
        konular.append("📄 Oturum izinleri")
    if any('süre' in y.lower() or 'bekle' in y.lower() or 'kaç yıl' in y.lower() for y in yorum_listesi):
        konular.append("⏰ Bekleme süreleri")
    if any('sınav' in y.lower() or 'sfi' in y.lower() or 'dil' in y.lower() for y in yorum_listesi):
        konular.append("📚 Dil şartı / SFI")
    if any('evlilik' in y.lower() or 'sambo' in y.lower() for y in yorum_listesi):
        konular.append("💑 Evlilik / Sambo yolu")
    if any('mahkeme' in y.lower() or 'dava' in y.lower() or 'itiraz' in y.lower() for y in yorum_listesi):
        konular.append("⚖️ Mahkeme / İtiraz")
    if any('çocuk' in y.lower() or 'çete' in y.lower() or 'uyuşturucu' in y.lower() for y in yorum_listesi):
        konular.append("👶 Çocuk güvenliği / Çeteler")
    if any('ceza' in y.lower() or 'trafik' in y.lower() or 'ehliyet' in y.lower() for y in yorum_listesi):
        konular.append("🚗 Trafik cezası etkisi")
    
    # Küfür eden yorumlar
    kufur_yapanlar = [(yorum_listesi[i], sonuclar[i]['kufur_kelimeler']) 
                      for i in range(len(yorum_listesi)) if sonuclar[i]['kufur']]
    
    # Özet metin
    print("\n" + "="*70)
    print("📊 YOUTUBE YORUM ANALİZ ÖZETİ")
    print("="*70)
    print(f"📅 Analiz Tarihi: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"📝 Toplam Yorum: {toplam}")
    print("")
    
    print("😊 DUYGU ANALİZİ")
    print("-"*40)
    print(f"😃 Olumlu: {olumlu} yorum ({olumlu/toplam*100:.1f}%)")
    print(f"😞 Olumsuz: {olumsuz} yorum ({olumsuz/toplam*100:.1f}%)")
    print(f"😐 Nötr: {notr} yorum ({notr/toplam*100:.1f}%)")
    
    # Basit grafik
    pos_bar = int(olumlu/toplam*20)
    neg_bar = int(olumsuz/toplam*20)
    print(f"Grafik:  {'😃' * pos_bar}{'😐' * (20-pos_bar-neg_bar)}{'😞' * neg_bar}")
    print("")
    
    print("📊 DİĞER METRİKLER")
    print("-"*40)
    print(f"❓ Soru içeren yorum: {sorular} ({sorular/toplam*100:.1f}%)")
    print(f"💡 Öneri içeren: {oneriler} ({oneriler/toplam*100:.1f}%)")
    print(f"🔧 Eleştiri içeren: {elestiriler} ({elestiriler/toplam*100:.1f}%)")
    print(f"⚠️ Küfür içeren: {kufur_var} ({kufur_var/toplam*100:.1f}%)")
    print("")
    
    if kufur_yapanlar:
        print("🚫 KÜFÜR İÇEREN YORUMLAR")
        print("-"*40)
        for i, (yorum, kelimeler) in enumerate(kufur_yapanlar[:5], 1):
            print(f"{i}. \"{yorum[:80]}...\"")
            print(f"   🔴 Küfürler: {', '.join(kelimeler)}")
        if len(kufur_yapanlar) > 5:
            print(f"   ... ve {len(kufur_yapanlar)-5} yorum daha")
        print("")
    
    print("🏷️ TESPİT EDİLEN KONULAR")
    print("-"*40)
    for konu in konular:
        print(f"   {konu}")
    print("")
    
    print("🔝 EN SIK GEÇEN KELİMELER")
    print("-"*40)
    for kelime, sayi in en_cok_kelimeler[:8]:
        print(f"   • {kelime}: {sayi} kez")
    print("")
    
    print("💡 ÖNE ÇIKAN SORULAR (Kullanıcıların merak ettikleri)")
    print("-"*40)
    soru_yorumlar = [y for i, y in enumerate(yorum_listesi) if sonuclar[i]['soru']]
    for soru in soru_yorumlar[:6]:
        print(f"   • {soru[:90]}...")
    print("")
    
    print("🔧 ÖNE ÇIKAN ELEŞTİRİLER")
    print("-"*40)
    elestiri_yorumlar = [y for i, y in enumerate(yorum_listesi) if sonuclar[i]['elestiri']]
    for elestiri in elestiri_yorumlar[:5]:
        print(f"   • {elestiri[:90]}...")
    print("")
    
    print("📌 3 MADDE İLE ÖZET")
    print("-"*40)
    ozet_maddeler = []
    
    if olumlu > olumsuz:
        ozet_maddeler.append(f"✅ Yorumların %{olumlu/toplam*100:.0f}'ı olumlu, izleyiciler içeriği faydalı buluyor.")
    else:
        ozet_maddeler.append(f"⚠️ Yorumların %{olumsuz/toplam*100:.0f}'ı olumsuz, ciddi memnuniyetsizlik var.")
    
    if 'vatandaşlık' in tum_metin:
        ozet_maddeler.append("🏛️ En çok tartışılan konu: Vatandaşlık şartları ve bekleme süreleri.")
    
    if 'mahkeme' in tum_metin or 'dava' in tum_metin:
        ozet_maddeler.append("⚖️ İzleyiciler yeni yasaları mahkemeye götürmeyi düşünüyor.")
    
    if 'çocuk' in tum_metin:
        ozet_maddeler.append("👶 Ciddi çocuk güvenliği endişeleri var (çeteler, uyuşturucu).")
    
    if kufur_var > 0:
        ozet_maddeler.append(f"⚠️ {kufur_var} yorum küfür içeriyor, gergin bir atmosfer var.")
    
    if not ozet_maddeler:
        ozet_maddeler.append("📊 Yorumlar genel olarak bilgi paylaşımı ve soru sorma üzerine.")
    
    for i, madde in enumerate(ozet_maddeler[:3], 1):
        print(f"   {i}. {madde}")
    
    print("")
    print("="*70)
    print("💬 GENEL DEĞERLENDİRME")
    print("="*70)
    
    if olumlu/toplam > 0.5:
        print("İzleyiciler genel olarak memnun ve içeriği faydalı buluyor.")
    elif olumsuz/toplam > 0.3:
        print("Ciddi bir memnuniyetsizlik var. İzleyiciler süreçlerden ve bekleme sürelerinden şikayetçi.")
    else:
        print("Karmaşık bir tablo var. İzleyiciler bilgi arıyor ama bazı konularda endişeli.")
    
    if sorular > toplam * 0.3:
        print("Çok sayıda soru var, izleyiciler belirsizlik yaşıyor ve net cevap arıyor.")
    
    if 'mahkeme' in tum_metin:
        print("Yasal yollara başvurma fikri gündemde, güven kaybı var.")
    
    print("")
    print("="*70)
    
    return {
        'toplam': toplam,
        'olumlu_yuzde': olumlu/toplam*100,
        'olumsuz_yuzde': olumsuz/toplam*100,
        'kufur_sayisi': kufur_var,
        'soru_sayisi': sorular,
        'konular': konular,
        'en_cok_kelimeler': en_cok_kelimeler
    }

# ==================== ÇALIŞTIR ====================

if __name__ == "__main__":
    print("\n🚀 YouTube Yorum Analiz Aracı başlatılıyor...")
    print(f"📊 {len(yorumlar)} yorum analiz edilecek.\n")
    
    sonuc = ozet_cikar(yorumlar)
    
    print("\n✅ Analiz tamamlandı!")
    print(f"📁 Rapor özeti yukarıda görüntülenmektedir.")
