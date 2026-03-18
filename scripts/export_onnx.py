"""
One-time script to export the YOLO .pt model to ONNX format.

Usage:
    python scripts/export_onnx.py

Prerequisites:
    pip install ultralytics

This script must be run before starting the main server.
The exported ONNX file will be used for all subsequent inference calls.
"""

import sys
import colorama
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (scripts/ 밖에서도 실행 가능하도록)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def export_model(pt_path: Path, output_path: Path, imgsz: int = 640) -> None:
    """YOLO .pt 모델을 ONNX 형식으로 변환한다.

    Args:
        pt_path: 원본 PyTorch 모델 파일 경로
        output_path: 저장할 ONNX 파일 경로
        imgsz: 모델 입력 이미지 크기
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        print("오류: ultralytics가 설치되어 있지 않습니다.")
        print("다음 명령어로 설치하세요: pip install ultralytics")
        sys.exit(1)

    if not pt_path.exists():
        print(f"오류: 모델 파일을 찾을 수 없습니다: {pt_path}")
        print("https://github.com/prodbykosta/ppe-safety-detection-ai 에서 best.pt를 다운로드하세요.")
        sys.exit(1)

    print(f"모델 로드 중: {pt_path}")
    model = YOLO(str(pt_path))

    print(f"ONNX 변환 중 (입력 크기: {imgsz}×{imgsz})...")
    exported_path = model.export(
        format="onnx",
        imgsz=imgsz,
        opset=17,
        simplify=True,
        dynamic=False,
    )

    # ultralytics가 기본적으로 .pt와 같은 위치에 저장하므로 필요 시 이동
    exported_path = Path(str(exported_path))
    if exported_path != output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        exported_path.rename(output_path)
        print(f"파일 이동: {exported_path} → {output_path}")

    print(f"\nONNX 변환 완료: {output_path}")

    # 변환된 모델 검증
    _verify_onnx(output_path, imgsz)


def _verify_onnx(onnx_path: Path, imgsz: int) -> None:
    """변환된 ONNX 모델로 더미 추론을 수행하고 클래스 정보를 출력한다."""
    try:
        import ast
        import numpy as np
        import onnxruntime as ort

        print("\n─── ONNX 모델 검증 ───────────────────────────────────────────")
        session = ort.InferenceSession(
            str(onnx_path),
            providers=["CPUExecutionProvider"],
        )

        # 입출력 정보 출력
        for inp in session.get_inputs():
            print(f"입력 | 이름: {inp.name} | 형태: {inp.shape} | 타입: {inp.type}")
        for out in session.get_outputs():
            print(f"출력 | 이름: {out.name} | 형태: {out.shape} | 타입: {out.type}")

        # 클래스 이름 출력
        meta = session.get_modelmeta().custom_metadata_map
        if "names" in meta:
            names_raw = meta["names"]
            parsed = ast.literal_eval(names_raw)
            print(f"\n감지 클래스: {parsed}")
            print("\n[!!]  중요: backend/models/onnx_detector.py의 _HELMET_LABELS, _JACKET_LABELS에")
            print("   위 클래스 이름이 포함되어 있는지 확인하세요.")
        else:
            print("\n[!!]  모델에 클래스 이름 메타데이터가 없습니다.")
            print("   backend/models/onnx_detector.py의 _HELMET_LABELS, _JACKET_LABELS를 수동으로 설정하세요.")

        # 더미 추론으로 런타임 오류 사전 확인
        dummy_input = np.random.rand(1, 3, imgsz, imgsz).astype(np.float32)
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name
        session.run([output_name], {input_name: dummy_input})

        print("\n[V] 더미 추론 성공 - 모델이 정상적으로 동작합니다.")
        print("─────────────────────────────────────────────────────────────\n")

    except Exception as e:
        print(f"\n[X] 모델 검증 실패: {e}")
        print("모델 파일이 올바른지 확인하세요.")


if __name__ == "__main__":
    colorama.init()

    # 기본 경로 설정 (프로젝트 루트 기준)
    MODELS_DIR = PROJECT_ROOT / "data" / "models"
    PT_PATH = MODELS_DIR / "best.pt"
    ONNX_PATH = MODELS_DIR / "best.onnx"

    export_model(PT_PATH, ONNX_PATH)
