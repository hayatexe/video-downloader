# Video Downloader

YouTube, TikTok, Instagram ve yt-dlp'nin desteklediği 1000+ siteden video
indiren, Windows için masaüstü uygulaması. Flask + pywebview ile yazıldı,
tek bir kurulum dosyası olarak dağıtılır.

## Kurulum

[Releases](../../releases/latest) sayfasından `Video Downloader Kurulum.exe`
dosyasını indirip çalıştırın.

> Uygulama kod imzası taşımadığı için Windows SmartScreen bir uyarı gösterebilir.
> **Daha fazla bilgi → Yine de çalıştır** ile devam edebilirsiniz.

## Özellikler

- Video + ses, yalnızca video ya da yalnızca ses indirme
- Ses formatları: MP3, M4A, WAV, OPUS, FLAC
- Kalite seçimi (1080p'ye kadar veya kaynağın en iyisi)
- Başlangıç/bitiş zamanı vererek kırpma
- Oynatma listesi desteği
- Uygulama içi giriş penceresi (Instagram gibi oturum isteyen siteler için)
- Tepsiye küçültme, koyu/açık tema

## Otomatik güncelleme

Uygulamanın iki ayrı güncelleme kanalı vardır:

| Kanal | Boyut | Ne zaman | Nasıl |
|---|---|---|---|
| **yt-dlp** | ~3 MB | Günde bir kez (açılışta) + indirme bozulduğu an | Sessiz, otomatik |
| **Uygulama** | ~70 MB | Yeni sürüm çıktığında | Arka planda iner, **bir sonraki açılışta sessizce kurulur** |

Uygulama kanalı artık hiçbir şey sormaz: siz indirme yaparken yeni sürümün
kurulum dosyası arka planda (boş bir anda) `%LOCALAPPDATA%\Video Downloader\updates`
altına iner. Uygulamayı bir dahaki açışınızda açılış ekranı "Güncelleme
kuruluyor" der, kurulum sessizce (`/VERYSILENT`) yapılır ve uygulama kendini
yeniden açar. Toplam gecikme birkaç saniyedir.

Kurulum iki kez denenip de sürüm değişmezse otomatik kurulumdan vazgeçilir
(açılış döngüsüne girmemek için) ve güncelleme **Ayarlar → Güncelleme**'den
elle kurulabilir halde bekler. Otomatik güncellemeyi **Ayarlar → Otomatik
Güncelleme** ile kapatabilirsiniz.

yt-dlp kanalı önemlidir: YouTube ve TikTok çıkarım yöntemlerini ayda birkaç
kez değiştirir ve eski bir yt-dlp `HTTP Error 403` ya da
`Unexpected response from webpage request` vermeye başlar. Bu yüzden yt-dlp
uygulamanın içine **gömülmez**; `%LOCALAPPDATA%\Video Downloader\runtime`
altından yüklenir ve oradan güncellenir — yani indirme motorunu güncellemek
için uygulamayı yeniden kurmanız gerekmez.

Bir çıkarım hatası alındığında (`403`, `Unexpected response`) yt-dlp
güncellemesi artık bir sonraki açılış beklenmeden **o anda** arka planda
indirilir; yeni sürüm bir sonraki açılışta devreye girer. **Ayarlar →
Güncelleme → Denetle** ile elle de tetikleyebilirsiniz.

> **Not:** TikTok ve Instagram'ın web çıkarımı `curl_cffi` ile yapılan tarayıcı
> taklidine (impersonation) ihtiyaç duyar. Bu paket eksikse yt-dlp güncel olsa
> bile TikTok `Unexpected response from webpage request` verir ve uygulama bunu
> "giriş gerekiyor" sanırdı. Artık pakete dahil ediliyor.

## Sürüm çıkarma (GitHub Actions)

Derleme artık kendi bilgisayarınızda yapılmak zorunda değil.
`.github/workflows/release.yml` Windows runner'da her şeyi yapar: bağımlılıkları
kurar, ffmpeg'i indirir, PyInstaller ile derler, `curl_cffi`'nin pakete girdiğini
doğrular, Inno Setup ile kurulum paketini üretir ve **GitHub Release** olarak
yayınlar.

Uygulamanın otomatik güncellemesi tam da bu Release'e baktığı için (`updater.py`
→ `/releases/latest`) yeni sürüm yayınlandığı anda kurulu uygulamalar kendini
günceller.

İki şekilde tetiklenir:

* `git tag v1.3.1 && git push origin v1.3.1`
* GitHub → **Actions → Release → Run workflow** → sürüm numarasını yazın

Sürüm numarası etiketten alınır ve derleme sırasında `updater.py` ile
`installer.iss` içine yazılır — iki dosyayı elle güncellemeyi unutma derdi yok.

## Kaynaktan çalıştırma

```
pip install -r requirements.txt
python launcher.pyw
```

## Derleme

`ffmpeg/` klasörü depoya dahil değildir (161 MB). Derlemeden önce
[BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases)
sayfasından `ffmpeg-master-latest-win64-gpl-shared.zip` indirin ve
arşivdeki `bin/` içeriğini — `ffplay.exe` hariç — `ffmpeg/` klasörüne kopyalayın.

Sonra:

```
build_exe.bat
```

Bu betik PyInstaller ile uygulamayı derler, ffmpeg'i yanına kopyalar ve
Inno Setup ile `dist\Video Downloader Kurulum.exe` paketini üretir.

### Paketleme hakkında iki not

- **yt-dlp PYZ'ye gömülmez.** `Video Downloader.spec` yt-dlp'yi normal şekilde
  analiz ettirir (bağımlılıkları doğru toplansın diye), ancak modüllerini
  `PYZ` oluşturulmadan hemen önce ayıklar ve kaynağı `runtime/` altına düz
  dosya olarak koyar. PyInstaller'ın `FrozenImporter`'ı `sys.meta_path`'te
  `sys.path`'ten önce geldiği için, gömülü kalsaydı çalışma zamanında
  güncellenmesi imkânsız olurdu.
- **ffmpeg PyInstaller ile paketlenmez.** "shared" build'in DLL'leri `datas`
  ile eklendiğinde PyInstaller onları `binaries`'e taşıyıp `_internal` köküne
  de kopyalıyor, yani 161 MB iki kere yazılıyordu. Bunun yerine ffmpeg
  derlemeden sonra çıktının yanına kopyalanır.

## Lisans

Bu uygulama [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense) ve
[FFmpeg](https://ffmpeg.org/) (GPL) kullanır. FFmpeg'in GPL derlemesi
paketlendiği için dağıtılan ikili GPL şartlarına tabidir.
