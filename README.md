# Video Downloader

YouTube, TikTok, Instagram ve yt-dlp'nin desteklediği 1000+ siteden video
indiren, Windows için masaüstü uygulaması. Flask + pywebview ile yazıldı,
tek bir kurulum dosyası olarak dağıtılır.

## Kurulum

[Releases](../../releases/latest) sayfasından `Video Downloader Kurulum.exe`
dosyasını indirip çalıştırın. Yönetici izni gerekmez; kendi kullanıcı
klasörünüze kurulur.

### Windows SmartScreen uyarısı

İlk kurulumda **"Windows bilgisayarınızı korudu"** uyarısı çıkar.
**Daha fazla bilgi → Yine de çalıştır** ile geçebilirsiniz.

Bu uyarı yalnızca **bir kez**, ilk kurulumda görünür. Sonrasındaki otomatik
güncellemelerde çıkmaz: uyarıyı tetikleyen şey dosyanın
*Mark-of-the-Web* işaretidir, bunu tarayıcılar indirirken ekler. Uygulamanın
kendi güncelleyicisi dosyayı doğrudan indirdiği için o işaret konmaz.

Uyarının sebebi kodun imzasız olması. İmzalamak için ücretli bir sertifika
gerekiyor ve Microsoft'un ucuz seçeneği (Artifact Signing, ~$10/ay) bireysel
geliştiriciler için yalnızca ABD ve Kanada'da açık. Bu yüzden şimdilik
imzasız dağıtılıyor.

### İndirdiğinizi doğrulamak

Her yayında kurulum dosyasının SHA256 toplamını içeren `SHA256SUMS.txt` var.
Karşılaştırmak için:

```powershell
Get-FileHash "Video Downloader Kurulum.exe" -Algorithm SHA256
```

Uygulamanın otomatik güncellemesi bu doğrulamayı **kendiliğinden** yapar ve
toplam uyuşmazsa kurulumu başlatmaz.

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

Güncelleme tek başına yetmez, çünkü `HTTP Error 403`'ün çoğu **geçicidir**:
YouTube'un verdiği imzalı indirme bağlantısı geçersizleşir. Aynı bağlantıyı
tekrar istemek işe yaramaz — yeniden *çıkarım* gerekir, yani taze bir
bağlantı almak. Uygulama bunu kendiliğinden yapıyor: böyle bir hatada
indirmeyi en fazla iki kez, artan beklemeyle yeniden dener. Kalıcı hatalarda
(video kaldırılmış vb.) boşa deneme yapmaz.

Üç deneme de 403 verirse bu artık gerçekten eskimiş bir yt-dlp'ye işaret eder.
Böyle bir durumda güncelleme artık bir sonraki açılış beklenmeden **o anda**
arka planda indirilir; yeni sürüm bir sonraki açılışta devreye girer.
**Ayarlar → Güncelleme → Denetle** ile elle de tetikleyebilirsiniz.

> **Not:** TikTok ve Instagram'ın web çıkarımı `curl_cffi` ile yapılan tarayıcı
> taklidine (impersonation) ihtiyaç duyar. Bu paket eksikse yt-dlp güncel olsa
> bile TikTok `Unexpected response from webpage request` verir ve uygulama bunu
> "giriş gerekiyor" sanırdı. Artık pakete dahil ediliyor.

## Sürüm çıkarma (GitHub Actions)

Derleme artık kendi bilgisayarınızda yapılmak zorunda değil.
`.github/workflows/release.yml` Windows runner'da her şeyi yapar: bağımlılıkları
kurar, ffmpeg'i indirir, PyInstaller ile derler, `curl_cffi`'nin pakete girdiğini
doğrular, Inno Setup ile kurulum paketini üretir, `SHA256SUMS.txt` hesaplar ve
ikisini birlikte **GitHub Release** olarak yayınlar.

Uygulamanın otomatik güncellemesi tam da bu Release'e baktığı için (`updater.py`
→ `/releases/latest`) yeni sürüm yayınlandığı anda kurulu uygulamalar kendini
günceller. SHA256 dosyası şart: uygulama indirdiği kurulumu doğrulayamazsa
güncellemeyi yapmaz.

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
