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
| **yt-dlp** | ~3 MB | Günde bir kez, açılışta | Sessiz, otomatik |
| **Uygulama** | ~70 MB | Yeni sürüm çıktığında | Sorar, onay sonrası kurar |

yt-dlp kanalı önemlidir: YouTube ve TikTok çıkarım yöntemlerini ayda birkaç
kez değiştirir ve eski bir yt-dlp `HTTP Error 403` ya da
`Unexpected response from webpage request` vermeye başlar. Bu yüzden yt-dlp
uygulamanın içine **gömülmez**; `%LOCALAPPDATA%\Video Downloader\runtime`
altından yüklenir ve oradan güncellenir — yani indirme motorunu güncellemek
için uygulamayı yeniden kurmanız gerekmez.

İndirmeler bozulursa **Ayarlar → Güncelleme → Denetle** ile yt-dlp'yi elle de
güncelleyebilirsiniz.

> **Not:** TikTok ve Instagram'ın web çıkarımı `curl_cffi` ile yapılan tarayıcı
> taklidine (impersonation) ihtiyaç duyar. Bu paket eksikse yt-dlp güncel olsa
> bile TikTok `Unexpected response from webpage request` verir ve uygulama bunu
> "giriş gerekiyor" sanırdı. Artık pakete dahil ediliyor.

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
