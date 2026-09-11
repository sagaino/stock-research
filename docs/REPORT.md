# Audit rekaman

```bash
uv run stockbit-report SESSION_ID
uv run stockbit-report --compare DEDICATED_ID WILDCARD_ID SYMBOL
```

Pembandingan membutuhkan sesi tertutup dan symbol dedicated yang sesuai.
Identitas transaksi adalah symbol + trade ID. Record tanpa ID dikecualikan dari
intersection dan jumlahnya dilaporkan. Duplikat ID dengan nilai konflik ditolak.
Harga, shares, side code, dan timestamp transaksi dibandingkan.

Irisan memakai timestamp transaksi terhadap batas waktu sesi lokal; offset jam
belum dikoreksi. Selisih received_at minus timestamp transaksi bukan latensi
jaringan terverifikasi. Selisih negatif perlu pemeriksaan jam/makna timestamp.

Sequence dan elapsed hanya memeriksa urutan lokal, bukan sequence bursa.
Kapasitas storage tetap **BELUM TERUKUR** tanpa durasi commit, backlog, dan
event-loop lag. Event timestamp sama bisa berasal dari satu pesan yang didecode
menjadi beberapa event. Tidak menyimpulkan server membuang pesan.

Volume/nilai menggunakan salinan pertama per identitas transaksi; fallback
tanpa ID adalah perkiraan. Velocity adalah bucket tetap waktu penerimaan client,
bukan waktu transaksi bursa; statistik bucket hanya mencakup bucket terisi.
Snapshot awal dapat menaikkan puncak. Spread/imbalance berbobot update, bukan
durasi, dan belum mengecualikan sisi stale. Locked (spread nol) dan crossed
(spread negatif) dilaporkan terpisah sebagai jumlah pengamatan, bukan episode.

Verdict mengikuti status sesi, keberadaan transaksi, anomali urutan, duplikasi,
dan hasil perbandingan bila tersedia. Tidak ada verdict kelengkapan absolut,
probabilitas profit, atau klaim akumulasi/distribusi dari net aggression saja.
Laporan bukan audit menyeluruh korupsi payload atau bukti kelengkapan pasar.

Hasil revisi Sesi 1 tanggal 7 September 2026 disimpan sebagai
`reports/quality_*_revised.md`. Laporan lama dipertahankan untuk pembandingan,
tetapi verdict lama HIGH INTEGRITY/AMAN tidak boleh dijadikan dasar keputusan.
Jika API berjalan tanpa auto-reload, restart proses API untuk memuat kode baru.
