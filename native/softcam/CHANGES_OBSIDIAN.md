# Changes by Obsidian Stream Hub (2026-11-19)

Source: https://github.com/tshino/softcam v1.8.1 (afb424c), MIT License (see LICENSE).

- Camera name "DirectShow Softcam" → "Obsidian Mirror Camera" (src/softcam/softcam.cpp, src/softcamcore/DShowSoftcam.cpp)
- Own filter CLSID {CCBD2AC3-77A1-4925-B6DF-78E0C090295F} so it never replaces another app's softcam
- Own shared memory / mutex names "Obsidian Mirror Camera/…" (src/softcamcore/FrameBuffer.cpp)
- Built as obsidian_camera64.dll / obsidian_camera32.dll by ../build_camera.ps1

Examples, tests and the Visual Studio 2019 project files from the original are kept unchanged.
- New sender call `scIdleSeconds` (seconds since an app last read a frame; header field
  `m_last_read_ms` in src/softcamcore/FrameBuffer.cpp, SenderAPI.cpp, softcam.cpp/.h/.def), so the
  program converts phone pictures only while some app is actually watching the camera
