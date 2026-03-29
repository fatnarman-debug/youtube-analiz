document.addEventListener('DOMContentLoaded', () => {

    // Modal ve Form Elementleri
    const modalOverlay = document.getElementById('purchaseModal');
    const closeModalBtn = document.getElementById('closeModalBtn');
    const openModalBtns = document.querySelectorAll('.open-modal-btn');
    
    // Değişken Alanlar
    const selectedPackageText = document.getElementById('selectedPackageText');
    const hiddenPackageName = document.getElementById('hiddenPackageName');
    
    // Form İşlemleri
    const purchaseForm = document.getElementById('purchaseForm');
    const submitBtn = document.getElementById('submitBtn');
    const formStatus = document.getElementById('formStatus');

    let currentStripeLink = ""; // Tıklanan paketin ödeme linki hafızada tutulacak

    // Modal Açma İşlemi
    openModalBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Butondaki data- özelliklerini oku
            const packageName = btn.getAttribute('data-package');
            const stripeUrl = btn.getAttribute('data-link');
            
            // Linki hafızaya al
            currentStripeLink = stripeUrl;
            
            // Modal içindeki yazıları güncelle
            selectedPackageText.innerHTML = `Seçilen Paket: <strong class="text-yellow">${packageName}</strong>`;
            hiddenPackageName.value = packageName;
            
            // Modalı göster
            modalOverlay.classList.add('active');
            
            // Mobilde kaymayı önle
            document.body.style.overflow = 'hidden';
        });
    });

    // Modal Kapatma Fonksiyonu
    const closeModal = () => {
        modalOverlay.classList.remove('active');
        document.body.style.overflow = 'auto'; // Kaymayı geri aç
        // Uyarı mesajlarını temizle
        formStatus.style.display = 'none';
        submitBtn.style.display = 'block';
        setTimeout(() => purchaseForm.reset(), 300); // 300ms animasyon süresi
    };

    // Modal Kapatma Eventleri
    closeModalBtn.addEventListener('click', closeModal);
    modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) {
            closeModal();
        }
    });

    // Form Gönderimi (AJAX ile Backend'e/Web3Forms'a)
    purchaseForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        // UI Durum Güncellemesi (Kullanıcı beklerken)
        submitBtn.style.display = 'none';
        formStatus.style.display = 'block';
        formStatus.innerHTML = '<p class="loading-text"><i class="fa-solid fa-spinner fa-spin"></i> Bilgileriniz iletiliyor, ödeme sayfasına yönlendiriliyorsunuz...</p>';
        
        const formAction = this.action;
        const formData = new FormData(this);

        try {
            // Arka planda veriyi gönder (Web3Forms API)
            const response = await fetch(formAction, {
                method: 'POST',
                body: formData,
            });
            
            const json = await response.json();
            
            if (response.status === 200) {
                // BAŞARILI DURUM
                // Bilgiler sahibine ulaştı, şimdi Stripes linkine yönlendir
                formStatus.innerHTML = '<p class="text-green"><i class="fa-solid fa-check-circle"></i> Başarılı! Ödeme sayfasına aktarılıyorsunuz...</p>';
                
                // Müşteriyi 1 saniye sonra stripe linkine yönlendir (deneyimi yumuşatmak için)
                setTimeout(() => {
                    window.location.href = currentStripeLink;
                }, 1000);
            } else {
                // API Hata döndü
                console.error("Web3Forms Hatası:", json);
                formStatus.innerHTML = '<p class="text-red"><i class="fa-solid fa-circle-exclamation"></i> Form gönderilirken bir hata oluştu. Lütfen bağlantınızı kontrol edip tekrar deneyin.</p>';
                submitBtn.style.display = 'block';
                submitBtn.innerHTML = 'Tekrar Dene';
            }
            
        } catch (error) {
            // Network hatası vb. durumlarda da Stripe linkine en kötü ihtimalle gönderelim mi?
            // "Kullanıcı bari ödemeyi yapsın" stratejisi de olabilir, fakat bilgileri gelmeyebilir.
            // O yüzden hata mesajı basmak daha profesyoneldir:
            console.error("Fetch Hatası", error);
            formStatus.innerHTML = '<p class="text-red"><i class="fa-solid fa-circle-exclamation"></i> Sistemsel bir hata oluştu veya e-posta anahtarınız eksik. Lütfen sayfayı yenileyiniz.</p>';
            submitBtn.style.display = 'block';
        }
    });

    // Sayfa içi smooth scrolling
    document.querySelectorAll('.navbar a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if(target) {
                target.scrollIntoView({
                    behavior: 'smooth'
                });
            }
        });
    });

});
