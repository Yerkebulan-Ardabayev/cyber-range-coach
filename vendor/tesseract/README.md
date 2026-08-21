# Проверка встроенного OCR для Windows

Установщик Windows включает проверенную и закреплённую версию Tesseract из этого
каталога. Обязательная точка входа: `vendor/tesseract/tesseract.exe`. Бинарные
файлы готовятся на Windows build host и не хранятся в этом репозитории.

`scripts/package-windows.ps1` намеренно завершается с ошибкой, если исполняемый
файл отсутствует. Это не позволяет выпустить установщик, который обещает локальный
OCR, но незаметно зависит от системной установки.

Закреплённые исходные файлы:

- Release asset Tesseract 5.5.3 для Windows x64:
  `https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe`, Apache-2.0.
- SHA-256 установщика: `bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4`.
- Commit `tessdata_fast`:
  `https://github.com/tesseract-ocr/tessdata_fast/tree/87416418657359cb625c412a48b6e1d6d41c29bd`.
- `eng.traineddata` SHA-256: `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`.
- `rus.traineddata` SHA-256: `e16e5e036cce1d9ec2b00063cf8b54472625b9e14d893a169e2b0dedeb4df225`.

`scripts/prepare-ocr.ps1 -ApproveDownload` проверяет каждый загруженный файл до
копирования. Используйте `-Force` только после проверки замены. Не добавляйте в
репозиторий непроверенные бинарные файлы.
