# HLS → RTSP Gateway v2.0

Mengubah sumber **HLS** (`.m3u8`), **YouTube Live**, dan **File MP4** menjadi endpoint
**RTSP** yang stabil dengan dashboard web modern. Dibangun untuk produksi di Seeed
reComputer **J4011 (Jetson Orin NX 8GB)** dengan dukungan encoding hardware NVENC.

**RTSP server: go2rtc** — konsisten ~0,3–1,3 dtk TTFF (Time-To-First-Frame), tanpa
lonjakan belasan detik seperti MediaMTX.

**Fitur baru v2.0:**
- **Source Type Picker** — pilih jenis sumber: **HLS**, **YouTube Live**, atau **File MP4**
- **Upload File MP4** — drag & drop, looping otomatis via go2rtc, maks 50MB
- **YouTube Auto-resolve** — deteksi & ekstrak URL HLS dari live stream YouTube via `yt-dlp`
- **Ambient Animated Background** — gradient orbs perlahan bergerak (40 detik loop), profesional & modern
- **Badge Indicators** — label visual untuk tiap sumber (📡 HLS, ▶ YouTube, 📁 File)
- **About Panel** — build info, versi, source code link

```
  ┌─ Sumber ──────────────────────────────────────────────────────────────┐
  │                                                                        │
  │  HLS (.m3u8) ──┐                                                       │
  │  YouTube Live ──┤──► go2rtc (FFmpeg: copy/transcode) ──► RTSP :8554   │
  │  File MP4    ──┘          ▲ add/remove via HTTP API (:1984)            │
  │                            │  ▲ status di-poll                         │
  │                   FastAPI backend ◄───── Dashboard (HTML+JS+CSS)       │
  │                        + SQLite (config persist)                       │
  │                        + watchdog (auto-restart)                       │
  └────────────────────────────────────────────────────────────────────────┘
```

---

## Struktur Proyek

| Path | Isi |
|---|---|
| `backend/app/` | FastAPI: API CRUD, klien go2rtc, ffprobe, builder source, watchdog, ytstream |
| `frontend/` | Dashboard statis (HTML + vanilla JS + CSS) |
| `config/go2rtc.yaml` | Konfigurasi go2rtc + template FFmpeg (input/output) |
| `systemd/` | Unit service untuk Jetson (perf lock, go2rtc, backend) |
| `docker-compose.yml` | Stack produksi untuk Linux / Jetson (`network_mode: host`) |
| `docker-compose.dev.yml` | Stack development (port berbeda agar tidak bentrok) |
| `docker-compose.windows.yml` | Override untuk Docker Desktop Windows (bridge network) |
| `data/` | **Bind mount** — SQLite database (aman di-restart) |
| `uploads/` | File MP4 yang diupload via dashboard |

---

## A. Coba cepat dengan Docker

### Development (port 8081, agar tidak bentrok dengan produksi)

```bash
docker compose -f docker-compose.dev.yml up --build
```

Buka dashboard: **http://localhost:8081** · go2rtc debug UI: **http://localhost:1986**
RTSP konsumen: `rtsp://<host>:8557/<nama>`

### Produksi (port 8080)

```bash
docker compose up --build -d
```

Buka dashboard: **http://localhost:8080** · go2rtc debug UI: **http://localhost:1984**
RTSP konsumen: `rtsp://<host>:8554/<nama>`

### Contoh uji coba

Tambahkan sumber H.264 publik:
1. Buka dashboard
2. Klik **HLS** → isi nama: `cam1`, URL: `https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8`
3. Klik **ADD**

Atau upload file MP4:
1. Klik **MP4 File**
2. Isi nama: `loop1`
3. Drag & drop file `.mp4` atau klik untuk pilih file
4. Klik **UPLOAD & ADD**

Putar hasilnya:
```bash
ffplay rtsp://localhost:8554/cam1
# atau VLC: Media → Open Network Stream → rtsp://<host>:8554/cam1
```

---

## B. Deploy ke Jetson Orin NX (produksi)

### 1. Lock performa Jetson
```bash
sudo cp systemd/jetson-perf.service /etc/systemd/system/
sudo systemctl enable --now jetson-perf
```

### 2. Pastikan ffmpeg dengan NVENC terpasang
```bash
ffmpeg -hide_banner -encoders | grep nvmpi   # harus muncul h264_nvmpi
ffmpeg -hide_banner -decoders | grep nvmpi   # h264_nvmpi, hevc_nvmpi
```
> Tanpa `nvmpi`, transcode/fast-start jatuh ke CPU (libx264). Gunakan Docker
> untuk produksi agar dependensi terisolasi.

### 3. Deploy via Docker (disarankan)
```bash
git clone https://github.com/chandramaulana/hls-to-rtsp-1.git /opt/hls-gateway
cd /opt/hls-gateway
# Sesuaikan RTSP_HOST di docker-compose.yml dengan IP publik Jetson
docker compose up --build -d
```

### 4. Buka dashboard
**http://<jetson-ip>:8080** — URL RTSP: `rtsp://<jetson-ip>:8554/<nama>`

Setelah reboot, semua stream pulih otomatis:
- Docker `restart: unless-stopped`
- Backend **watchdog** reconcilasi dari SQLite
- go2rtc memuat stream dari `config/go2rtc.yaml`

---

## Dashboard — Panduan Fitur

### Source Type Picker

Tiga jenis sumber yang didukung:

| Tipe | Deskripsi | Input |
|---|---|---|
| **📡 HLS** | CCTV / M3U8 Link | URL `.m3u8` |
| **▶ YouTube** | YouTube Live Stream | URL YouTube (resolusi otomatis ke HLS) |
| **📁 MP4 File** | Upload file & looping | File `.mp4/.mov/.avi/.mkv/.ts` (maks 50MB) |

### Opsi Lanjutan (Advanced)

| Opsi | Nilai | Fungsi |
|---|---|---|
| **Mode** | `auto` / `copy` / `transcode` | Strategi penanganan video |
| **Audio** | `aac` / `copy` / `drop` | Penanganan audio |
| **Fast Start** | on/off | Re-encode keyframe tiap 1 dtk (play instan) |
| **Low Latency** | on/off | Ikuti live-edge (minim buffering) |

### Animated Background

Dashboard memiliki **ambient gradient animation** 40 detik:
- 4 lapis gradient orb (biru, hijau, amber) yang perlahan **drift & scale**
- Sangat subtle (3–8% opacity) — tidak ganggu readability
- Panel tetap solid, animasi hanya di background area

---

## Source Types — Detail Teknis

### HLS (Mode Otomatis)
Backend menjalankan `ffprobe` untuk deteksi codec sumber:
- **H.264** → mode `copy` (passthrough, beban CPU minimal)
- **H.265/HEVC** → mode `transcode` otomatis ke H.264
- Template input: `hlslive` (stabil, tahan buffer 30 dtk)

### YouTube Live
Menggunakan `yt-dlp` untuk resolve URL YouTube live stream ke HLS m3u8 langsung.
- Stream asli disimpan sebagai `original_url` untuk referensi
- Path: `backend/app/ytstream.py`
- Fallback: jika resolve gagal, URL asli tetap dicoba sebagai HLS biasa

### File MP4
File diupload ke `uploads/` dan di-streaming via go2rtc dengan **looping otomatis**.
- go2rtc otomatis restart FFmpeg saat file selesai diputar
- Format yang didukung: `.mp4`, `.mov`, `.avi`, `.mkv`, `.ts`, `.m4v`
- Maks 50MB per file
- File disimpan dengan UUID (nama unik), nama asli ditampilkan di dashboard

---

## API Backend

| Method | Path | Fungsi | v2.0 |
|---|---|---|---|
| `POST` | `/api/sources` | Tambah sumber (HLS/YouTube/File) | ✅ |
| `GET` | `/api/sources` | List semua sumber + status | ✅ |
| `GET` | `/api/sources/{id}` | Detail satu sumber | ✅ |
| `PATCH` | `/api/sources/{id}` | Edit sumber | ✅ |
| `POST` | `/api/sources/{id}/restart` | Restart stream | ✅ |
| `POST` | `/api/sources/{id}/stop` | Stop stream (hapus dari go2rtc) | ✅ |
| `DELETE` | `/api/sources/{id}` | Hapus sumber + file fisik | ✅ |
| `POST` | `/api/upload` | Upload file MP4 | **baru** |
| `GET` | `/health` | Health check service | ✅ |

### Upload Endpoint

```
POST /api/upload
Content-Type: multipart/form-data

file: <binary .mp4/.mov/.avi/.mkv/.ts>

Response: { status, file_path, file_name, size }
```

File yang diupload bisa langsung dipakai sebagai `hls_url` pada `POST /api/sources`
dengan `source_type: "file"`.

---

## Konfigurasi (Environment Variables)

| Var | Default | Keterangan |
|---|---|---|
| `G2R_API_URL` | `http://localhost:1984` | API kontrol go2rtc |
| `RTSP_HOST` | `localhost` | Host yang ditampilkan di URL RTSP |
| `RTSP_PORT` | `8554` | Port RTSP |
| `DB_PATH` | `/app/data/gateway.db` | Lokasi SQLite |
| `UPLOADS_DIR` | `/app/uploads` | Direktori upload file MP4 |
| `WATCHDOG_ENABLED` | `1` | Aktifkan reconcile-loop |
| `WATCHDOG_INTERVAL` | `30` | Detik antar-cek reconcile |
| `GOP_FRAMES` | `30` | Keyframe interval (≈1 dtk @30fps) |
| `MAX_TRANSCODE` | `12` | Batas konkurensi encode NVENC |

---

## Database (SQLite)

Sumber stream disimpan di `data/gateway.db` (bind mount — aman di restart).

**Tabel `sources`:**

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | TEXT (UUID) | Primary key |
| `name` | TEXT | Nama stream (unik) |
| `hls_url` | TEXT | URL sumber / path file |
| `source_type` | TEXT | `hls` / `youtube` / `file` |
| `original_url` | TEXT | URL asli (untuk YouTube) |
| `file_path` | TEXT | Path file MP4 |
| `mode` | TEXT | `auto` / `copy` / `transcode` |
| `active_mode` | TEXT | Mode yang aktif setelah ffprobe |
| `audio` | TEXT | `aac` / `copy` / `drop` |
| `fast_start` | INTEGER | Keyframe tiap 1 dtk (bool) |
| `low_latency` | INTEGER | Live-edge mode (bool) |
| `source_codec` | TEXT | Hasil ffprobe |
| `width` / `height` | INTEGER | Resolusi hasil ffprobe |
| `last_error` | TEXT | Error terakhir |
| `enabled` | INTEGER | Stream aktif/tidak |
| `created_at` | TEXT | Timestamp |

Migrasi inkremental: kolom baru akan ditambahkan otomatis saat backend pertama
kali jalan dengan versi baru.

---

## Docker Compose — Catatan Penting

### Volume Bind Mounts

| Volume | Container | Tujuan |
|---|---|---|
| `./data:/app/data` | api | Database SQLite (persisten) |
| `./uploads:/app/uploads` | api | Upload file MP4 |
| `./uploads:/app/uploads:ro` | go2rtc | **Akses baca file MP4** (wajib agar RTSP bisa play) |
| `./config/go2rtc.yaml:/config/go2rtc.yaml` | go2rtc | Konfigurasi + persistensi stream |

> **⚠️ go2rtc HARUS punya akses ke folder uploads.** Tanpa volume mount ini,
> go2rtc akan gagal memutar file MP4 karena file tidak ditemukan.

### Network Mode

- **Linux / Jetson**: `network_mode: host` — performa maksimal, port langsung ke host
- **Docker Desktop (Windows/Mac)**: gunakan `docker-compose.windows.yml` (bridge + port mapping)

---

## Stabilitas & Tuning

### Anti-Putus (Buffer Tolerance)

Template `hlslive` di `go2rtc.yaml` di-tuning agar tahan buffer 5–30 dtk:
- `-rw_timeout 30000000` (30 dtk timeout read)
- `-reconnect 1 -reconnect_streamed 1` (reconnect otomatis)
- `-reconnect_delay_max 30` (delay reconnect maks 30 dtk)
- `-m3u8_hold_counters 60` (tahan playlist lawas saat error)

Filosofi: **lebih baik menunggu sumber pulih daripada restart** (restart bikin putus).

### Fast Start (Instant Play)

Untuk sumber dengan GOP panjang (keyframe jarang), centang **Fast Start**:
- Re-encode keyframe tiap 30 frame (~1 dtk)
- Play RTSP jadi <400 ms konsisten
- Menggunakan encoder hardware (NVENC) atau software (libx264) sesuai ketersediaan

### Watchdog

Backend menjalankan watchdog loop setiap 30 dtk:
- Rekonsiliasi stream di go2rtc dengan database
- Restart stream yang mati
- Update status & error terbaru

---

## Kenapa go2rtc (bukan MediaMTX)

Diukur pada sumber CCTV nyata, play-time dari klien jaringan (TTFF):

| Play # | MediaMTX | go2rtc |
|---|---|---|
| #1 | 13.981 ms | 464 ms |
| #3 | 16.261 ms | 349 ms |
| #5 | 16.551 ms | 326 ms |
| typical | 261 – **16.551 ms (acak)** | **286 – 1.295 ms (konsisten)** |

MediaMTX menimbulkan lonjakan belasan detik yang membuat sebagian VMS gagal connect.
go2rtc tidak — itu alasan penggantian.

**Karakter go2rtc:**
- **On-demand**: producer (FFmpeg) baru jalan saat ada klien pertama, idle saat tidak
  ditonton. `bytes_received` = 0 saat idle = normal.
- **Multi-viewer**: satu stream bisa ditonton banyak klien (fan-out).
- **Persistensi**: stream yang ditambah via API tersimpan ke `config/go2rtc.yaml`.
- **File looping**: go2rtc otomatis restart FFmpeg saat file MP4 selesai diputar.

---

## Keamanan

- `config/go2rtc.yaml` saat ini tanpa autentikasi (cocok untuk dev / jaringan tepercaya)
- Untuk produksi: aktifkan autentikasi go2rtc, batasi akses API `:1984` ke localhost
- Dashboard bisa diletakkan di belakang reverse proxy + HTTPS

---

## Catatan Latency

Konversi HLS → RTSP **tidak** menghilangkan latency bawaan HLS (segmen 2–10 dtk =
*floor* latency). Gateway hanya menambah puluhan milidetik. Jitter buffer klien
(VLC ~1 dtk) ada di sisi konsumen, bukan gateway.
