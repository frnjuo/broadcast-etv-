#!/usr/bin/env bash
# Сборка MP4 из кадров tools/render.cjs и общего шоурила.
set -e
cd "$(dirname "$0")/.."
names=(01_zastavka_kanala 02_verdikt 03_gadzhetoteka 04_otbivka)
for n in "${names[@]}"; do
  ffmpeg -loglevel error -y -framerate 30 -i "frames/$n/%04d.png" -c:v libx264 -pix_fmt yuv420p -crf 15 -preset slow -movflags +faststart "video/ETV_$n.mp4"
done
ffmpeg -loglevel error -y $(for n in "${names[@]}"; do echo -i "video/ETV_$n.mp4"; done) \
  -filter_complex "[0][1][2][3]concat=n=4:v=1[v]" -map "[v]" -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart video/ETV_paket_showreel.mp4
ls -la video
