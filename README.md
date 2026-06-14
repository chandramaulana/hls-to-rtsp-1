# HLS → RTSP Gateway

Mengubah sumber **HLS** (`.m3u8`) menjadi endpoint **RTSP** yang stabil, dengan
dashboard web sederhana. Implementasi dari **PRD v1.0** + **Addendum Reliability Hardening**.
Target produksi: Seeed reComputer **J4011 (Jetson Orin NX 8GB)**.

**RTSP server: go2rtc** (mengganti MediaMTX). MediaMTX terbukti menimbulkan lonjakan
play-time 13-16 detik yang acak (mesin/VMS gagal connect); go2rtc konsisten ~0,3-1,3 detik
pada sumber & jaringan yang sama. Lihat bagian "Kenapa go2rtc" di bawah.

- **COPY** (passthrough) untuk sumber H.264 — beban minimum.
- **TRANSCODE** H.265→H.264 via hardware Jetson (NVENC `nvmpi`); di laptop fallback `libx264`.
- **Fast start**: re-encode keyframe tiap 1 dtk → play RTSP instan untuk sumber GOP-panjang.
- Auto-reconnect & restart producer dikelola go2rtc; rekonsiliasi backend setelah reboot.

```
Sumber HLS ──► go2rtc (FFmpeg per-stream: copy/transcode) ──► RTSP :8554 ──► VMS/NVR/VLC/DeepStream
                    ▲ add/remove via HTTP API (:1984)            ▲ status di-poll
          FastAPI backend  ◄──────────  Dashboard (HTML+JS)
                + SQLite (config persist)
```

## Struktur

| Path | Isi |
|---|---|
| `backend/app/` | FastAPI: API CRUD, klien go2rtc, ffprobe, builder source, reconcile-loop |
| `frontend/` | Dashboard statis (HTML + vanilla JS) |
| `config/go2rtc.yaml` | Konfigurasi go2rtc + template FFmpeg (input/encode) |
| `systemd/` | Unit service untuk Jetson (perf lock, go2rtc, backend) |
| `docker-compose*.yml` | Stack untuk dev di laptop |

---

## A. Coba cepat di laptop (Windows + Docker Desktop)

Mode **COPY & fast-start berfungsi penuh** di laptop. Mode **TRANSCODE/fast-start** di
laptop otomatis pakai software encoder **`libx264`** (encoder Jetson `nvmpi` tidak ada di
x86). Di Jetson, backend otomatis memilih **NVENC hardware** (deteksi `ffmpeg -encoders | grep nvmpi`).

```powershell
docker compose -f docker-compose.yml -f docker-compose.windows.yml up --build
```

Buka dashboard: **http://localhost:8080** · go2rtc web UI (debug): **http://localhost:1984**

Tambahkan sumber uji H.264 publik:
- Nama: `cam1`
- URL HLS: `https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8`
- Mode: `auto`

Putar hasilnya:

```powershell
ffplay rtsp://localhost:8554/cam1
# atau VLC: Media ▸ Open Network Stream ▸ rtsp://localhost:8554/cam1
```

Hentikan: `docker compose -f docker-compose.yml -f docker-compose.windows.yml down`

> **Catatan jaringan:** `docker-compose.windows.yml` memakai jaringan *bridge* + port
> mapping karena host networking tidak didukung penuh di Docker Desktop. Di Linux/Jetson,
> `docker-compose.yml` saja sudah memakai `network_mode: host`.

---

## B. Deploy ke Jetson Orin NX (produksi)

1. **Lock performa** (Addendum §1):
   ```bash
   sudo cp systemd/jetson-perf.service /etc/systemd/system/
   sudo systemctl enable --now jetson-perf
   ```

2. **Pasang go2rtc** (rilis arm64) ke `/usr/local/bin/go2rtc`, salin config:
   ```bash
   sudo cp config/go2rtc.yaml /usr/local/etc/go2rtc.yaml
   sudo cp systemd/go2rtc.service /etc/systemd/system/
   ```

3. **Pasang jetson-ffmpeg** (encoder/decoder hardware `nvmpi`) dan verifikasi.
   go2rtc memakai `ffmpeg` dari PATH, jadi pastikan ffmpeg ber-`nvmpi` yang dipakai:
   ```bash
   ffmpeg -hide_banner -encoders | grep nvmpi   # harus muncul h264_nvmpi
   ffmpeg -hide_banner -decoders | grep nvmpi   # h264_nvmpi, hevc_nvmpi
   ```
   > Tanpa `nvmpi`, transcode/fast-start jatuh ke CPU (libx264, berat). Template
   > `faststart_hw` di `go2rtc.yaml` memakai `h264_nvmpi` — backend memilihnya otomatis
   > bila ffmpeg-nya mendukung.

4. **Backend**:
   ```bash
   sudo mkdir -p /opt/hls-gateway && sudo cp -r backend/app frontend /opt/hls-gateway/
   cd /opt/hls-gateway && python3 -m venv .venv
   .venv/bin/pip install -r /path/to/backend/requirements.txt
   sudo cp systemd/hls-gateway-api.service /etc/systemd/system/
   # sesuaikan RTSP_HOST di unit file ke IP Jetson
   sudo systemctl enable --now go2rtc hls-gateway-api
   ```

5. Buka dashboard di `http://<jetson-ip>:8080`. URL RTSP konsumen:
   `rtsp://<jetson-ip>:8554/<nama>`.

Setelah reboot, semua stream pulih otomatis: systemd (`Restart=always`) + rekonsiliasi
backend dari SQLite + go2rtc mendaftar ulang stream.

---

## API Backend

| Method | Path | Fungsi |
|---|---|---|
| `POST` | `/api/sources` | Tambah → ffprobe → tentukan mode → add stream go2rtc |
| `GET` | `/api/sources` | List + status (DB + go2rtc) |
| `GET` | `/api/sources/{id}` | Detail |
| `PATCH` | `/api/sources/{id}` | Edit (replace stream) |
| `POST` | `/api/sources/{id}/restart` | Restart stream |
| `POST` | `/api/sources/{id}/stop` | Stop (hapus dari go2rtc, simpan di DB) |
| `DELETE` | `/api/sources/{id}` | Hapus stream + DB |
| `GET` | `/health` | Health service |

## Konfigurasi (environment variable)

| Var | Default | Keterangan |
|---|---|---|
| `G2R_API_URL` | `http://localhost:1984` | API kontrol go2rtc |
| `RTSP_HOST` | `localhost` | Host yang ditampilkan di URL RTSP ke operator |
| `RTSP_PORT` | `8554` | Port RTSP |
| `DB_PATH` | `./data/gateway.db` | Lokasi SQLite |
| `WATCHDOG_ENABLED` | `1` | Aktifkan reconcile-loop |
| `WATCHDOG_INTERVAL` | `30` | Detik antar-cek reconcile |
| `GOP_FRAMES` | `30` | Keyframe interval untuk transcode/fast-start (30 ≈ 1 dtk @30fps) |
| `MAX_TRANSCODE` | `12` | Batas konkurensi encode (transcode+fast_start, kapasitas NVENC) |

## Kenapa go2rtc (bukan MediaMTX)

Diukur pada sumber CCTV nyata, play-time dari klien jaringan (TTFF):

| Play # | MediaMTX | go2rtc |
|---|---|---|
| #1 | 13.981 ms | 464 ms |
| #3 | 16.261 ms | 349 ms |
| #5 | 16.551 ms | 326 ms |
| typical | 261 ms **– 16.551 ms (acak)** | **286 – 1.295 ms (konsisten)** |

MediaMTX menimbulkan lonjakan belasan detik yang membuat sebagian VMS gagal connect.
go2rtc tidak — itu alasan penggantian.

**Karakter go2rtc yang perlu diketahui:**
- **On-demand**: producer (FFmpeg) baru jalan saat ada klien pertama, idle saat tidak
  ditonton. Karena itu `bytes_received` 0 saat idle = **normal**, bukan freeze.
- **Multi-viewer**: satu stream bisa ditonton banyak klien (fan-out) di satu port `:8554`.
- **Persistensi**: stream yang ditambah via API tersimpan ke `config/go2rtc.yaml`.

## Play RTSP lambat? Aktifkan "Fast start"

Gejala: klik play butuh beberapa detik, sebagian mesin gagal. Penyebab: **GOP sumber
panjang** (keyframe jarang) — klien menunggu keyframe sebelum bisa menampilkan gambar.

**Solusi:** centang **Fast start** pada stream. Backend memilih template `faststart_*`
(re-encode keyframe tiap 1 dtk), play jadi <400 ms konsisten. Biaya: membebani encoder
seperti transcode — pakai hanya untuk sumber bermasalah; sisanya biarkan **copy**.

## Stabilitas (anti putus saat sumber buffer)

Template `hlslive` di `go2rtc.yaml` di-tuning agar tahan saat sumber buffer 5-30 detik:
`-rw_timeout 30s`, `-reconnect*`, `-reconnect_delay_max 30`, `-m3u8_hold_counters 60`.
Filosofi: **lebih baik menunggu sumber pulih daripada restart** (restart justru bikin
putus). Untuk sumber yang butuh latency minimum & stabil, pakai opsi **Low-latency**
(template `hlslowlat`: ikuti live-edge).

## Keamanan

`config/go2rtc.yaml` saat ini tanpa autentikasi (cocok dev / jaringan tepercaya). Untuk
produksi: aktifkan autentikasi go2rtc, batasi akses API (`:1984`) ke localhost via
firewall, dan letakkan dashboard di belakang login admin / reverse proxy.

## Catatan latency

Konversi HLS→RTSP **tidak** menghilangkan latency bawaan HLS (segmen 2–10 dtk =
*floor* latency). Gateway hanya menambah puluhan milidetik. Jitter buffer klien (VLC ~1s)
ada di sisi konsumen, bukan gateway. Lihat Addendum §0.
