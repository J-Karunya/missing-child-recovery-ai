# Troubleshooting

## IMPLEMENTED NOW

### `EOFError: Ran out of input`

This means PyTorch tried to read an empty or incomplete YOLO `.pt` weights file. Do not edit its binary contents. Retrieve a clean official model, then validate it:

```powershell
python services/detector.py --download
python services/detector.py
```

The second command should print `YOLO MODEL OK`. The project expects the model at `models/yolov8n.pt`. The downloader uses Ultralytics' supported `YOLO("yolov8n.pt")` mechanism, saves only after a temporary download passes the file-size check, and requires internet access.

### Empty, corrupted, or missing YOLO model

`detector.py` checks for a missing file and rejects files smaller than 1 MB before calling YOLO. It can recover automatically when `cctv_matcher.py` starts, but running the explicit download command first makes setup clearer. Do not copy a `.pt` file from an untrusted source or use an absolute user path.

### Ultralytics settings warning

A message such as `NoUltralytics setting 'openvino_msg'` normally means an older settings JSON contains a key unknown to the installed Ultralytics version. Ultralytics recreating its settings file is usually harmless and is separate from an empty-model `EOFError`. If it repeats after the model loads, use the version checks below before changing dependencies.

### Model path or video path errors

Run commands from the project root. The model path is project-relative: `models/yolov8n.pt`; the video is a simple filename under `data/cctv_videos`. Check `CCTV_VIDEO_FILE` and `MISSING_CHILD_ID` environment variables for typing errors.

### Dependency compatibility

Use the same virtual environment used for successful embedding generation. Inspect installed versions before changing anything:

```powershell
python --version
python -c "import numpy, torch, ultralytics, insightface, onnxruntime; print('numpy', numpy.__version__); print('torch', torch.__version__); print('ultralytics', ultralytics.__version__); print('insightface', insightface.__version__); print('onnxruntime', onnxruntime.__version__)"
python -m pip show deep-sort-realtime
```

Do not upgrade all packages as a first response, and avoid NumPy 2.2.x if it conflicts with your installed computer-vision packages.

### Independent YOLO verification

After model setup, either command loads the local model and should succeed:

```powershell
python services/detector.py
python -c "from services.detector import get_detector; get_detector(download_if_needed=False); print('YOLO MODEL OK')"
```

Then run `python services/cctv_matcher.py`. It should reach `Monitoring child ID: MC001`; zero potential matches is a valid outcome.

## PLANNED FUTURE

There is no production model registry, automatic dependency updater, cloud model hosting, or dashboard diagnostics in this prototype.
