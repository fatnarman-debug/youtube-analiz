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

    // Form Gönderimi (FastAPI Backend'e)
    purchaseForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        // UI Durum Güncellemesi
        submitBtn.style.display = 'none';
        formStatus.style.display = 'block';
        formStatus.innerHTML = '<p class="loading-text"><i class="fa-solid fa-spinner fa-spin"></i> Bilgileriniz kaydediliyor, ödeme sayfasına yönlendiriliyorsunuz...</p>';
        
        const formAction = this.action;
        const formData = new FormData(this);

        try {
            // Veriyi kendi sunucumuza gönder
            const response = await fetch(formAction, {
                method: 'POST',
                body: formData,
            });
            
            const result = await response.json();
            
            if (response.ok) {
                // BAŞARILI DURUM
                formStatus.innerHTML = '<p class="text-green"><i class="fa-solid fa-check-circle"></i> Başarılı! Ödeme sayfasına aktarılıyorsunuz...</p>';
                
                // Müşteri Panelinı 1 saniye sonra stripe linkine yönlendir
                setTimeout(() => {
                    let finalUrl = currentStripeLink;
                    if (typeof CURRENT_USER_ID !== 'undefined' && CURRENT_USER_ID) {
                        const separator = finalUrl.includes('?') ? '&' : '?';
                        finalUrl = `${finalUrl}${separator}client_reference_id=${CURRENT_USER_ID}`;
                    }
                    window.location.href = finalUrl;
                }, 1000);
            } else {
                // Backend hata döndü
                console.error("Sunucu Hatası:", result);
                formStatus.innerHTML = `<p class="text-red"><i class="fa-solid fa-circle-exclamation"></i> ${result.detail || 'Bir hata oluştu. Lütfen tekrar deneyin.'}</p>`;
                submitBtn.style.display = 'block';
                submitBtn.innerHTML = 'Tekrar Dene';
            }
            
        } catch (error) {
            console.error("Bağlantı Hatası", error);
            formStatus.innerHTML = '<p class="text-red"><i class="fa-solid fa-circle-exclamation"></i> Sunucuya bağlanılamadı. Lütfen internetinizi kontrol edip sayfayı yenileyiniz.</p>';
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
