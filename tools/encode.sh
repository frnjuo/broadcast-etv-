#!/usr/bin/env bash
# Сборка MP4 из кадров tools/render.cjs.
set -e
cd "$(dirname "$0")/.."
names=(01_zastavka_kanala 02_verdikt 03_gadzhetoteka 04_otbivka 05_logotip)
for n in "${names[@]}"; do
  ffmpeg -loglevel error -y -framerate 30 -i "frames/$n/%04d.png" -c:v libx264 -pix_fmt yuv420p -crf 15 -preset slow -movflags +faststart "video/ETV_$n.mp4"
done
ls -la video
