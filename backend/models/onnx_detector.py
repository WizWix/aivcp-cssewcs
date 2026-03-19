"""
ONNX-based PPE detector wrapper.
Handles model loading, preprocessing, inference, postprocessing, and visualization.
"""

import logging
from dataclasses import dataclass
from typing import cast, Dict, List

import cv2
import numpy as np
import onnxruntime as ort

from backend.models.schemas import ComplianceResult, Detection

# Optional Ultralytics for person detection
try:
    from ultralytics import YOLO
    _ULTRA_AVAILABLE = True
except ImportError:
    _ULTRA_AVAILABLE = False
    logger.warning("Ultralytics not available, person detection will use fallback")

logger = logging.getLogger(__name__)

# 바운딩 박스 색상 (BGR): 착용 여부에 따라 구분
_COLOR_COMPLIANT = (0, 200, 0)  # 초록: 정상 착용
_COLOR_VIOLATION = (0, 0, 220)  # 빨강: 미착용 위반
_COLOR_ITEM = (255, 150, 0)  # 하늘: 감지된 보호구 항목

# 헬멧 착용 클래스 키워드 (부분 문자열 매칭)
# "Hardhat", "hard-hat", "helmet", "Hard Hat" 등 모두 포괄
_HELMET_KEYWORDS = {"helmet", "hardhat", "hard-hat", "hard_hat"}

# 조끼 착용 클래스 키워드
# "Safety Vest", "safety-vest", "vest" 등 포괄
_JACKET_KEYWORDS = {"vest", "jacket", "safety-vest", "safety_vest"}

# 헬멧 미착용 명시 클래스 키워드 (NO-Hardhat, no helmet 등)
# 이 키워드가 레이블에 포함되면 명시적 위반으로 처리한다
_NO_HELMET_KEYWORDS = {"no-hardhat", "no_hardhat", "no hardhat", "no-helmet", "no_helmet", "no helmet"}

# 조끼 미착용 명시 클래스 키워드
_NO_JACKET_KEYWORDS = {"no-safety vest", "no_safety_vest", "no safety vest",
                       "no-vest", "no_vest", "no vest",
                       "no-jacket", "no_jacket", "no jacket"}


def _label_matches(label: str, keywords: set[str]) -> bool:
    """레이블 문자열이 키워드 집합 중 하나를 포함하는지 검사한다 (대소문자 무시)."""
    lower = label.lower()
    return any(kw in lower for kw in keywords)


@dataclass
class Box:
    """Bounding box with coordinates and metadata."""
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    class_id: int
    label: str

    def xyxy(self) -> tuple[int, int, int, int]:
        return self.x1, self.y1, self.x2, self.y2

    def w(self) -> int:
        return self.x2 - self.x1

    def h(self) -> int:
        return self.y2 - self.y1


class PersonDetector:
    """Person detection using Ultralytics YOLO or OpenCV HOG fallback."""

    def __init__(self, weights: str | None = None, conf: float = 0.45):
        self.conf = conf
        self.use_ultra = _ULTRA_AVAILABLE and weights is not None
        if self.use_ultra:
            try:
                self.model = YOLO(weights)
                dummy = np.zeros((640, 640, 3), dtype=np.uint8)
                _ = self.model(dummy, conf=self.conf, verbose=False)
                logger.info("Person detector: Ultralytics")
            except Exception as e:
                logger.warning(f"Ultralytics person model failed: {e}. Falling back to HOG.")
                self.use_ultra = False
        if not self.use_ultra:
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            logger.info("Person detector: OpenCV HOG fallback")

    def detect(self, frame: np.ndarray) -> list[Box]:
        """Detect persons in the frame."""
        H, W = frame.shape[:2]
        out: list[Box] = []
        if self.use_ultra:
            res = self.model(frame, conf=self.conf, verbose=False)
            for r in res:
                names = r.names if hasattr(r, 'names') else {}
                for b in r.boxes:
                    x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
                    c = float(b.conf[0])
                    cls = int(b.cls[0])
                    label = names.get(cls, str(cls))
                    if label == 'person':
                        x1, y1, x2, y2 = self._clip_box((x1, y1, x2, y2), W, H)
                        out.append(Box(x1, y1, x2, y2, c, cls, 'person'))
        else:
            # HOG fallback
            rects, weights = self.hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
            for (x, y, w, h), c in zip(rects, weights):
                if w < 32 or h < 64:
                    continue
                ar = h / max(1e-6, w)
                if ar < 1.2:
                    continue
                x1, y1, x2, y2 = self._clip_box((x, y, x + w, y + h), W, H)
                out.append(Box(x1, y1, x2, y2, float(c), 0, 'person'))
        return out

    @staticmethod
    def _clip_box(b: tuple[int, int, int, int], W: int, H: int) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = b
        return max(0, x1), max(0, y1), min(W, x2), min(H, y2)


@dataclass
class Track:
    id: int
    box: Box
    age: int = 0
    hits: int = 1


class IoUTracker:
    def __init__(self, iou_th: float = 0.3, max_age: int = 20):
        self.iou_th = iou_th
        self.max_age = max_age
        self.tracks: Dict[int, Track] = {}
        self.next_id = 0

    def update(self, detections: List[Box]) -> Dict[int, Box]:
        matched = {}
        used = set()
        for tid, track in list(self.tracks.items()):
            track.age += 1
            if track.age > self.max_age:
                del self.tracks[tid]
                continue
            best_iou = 0
            best_det = None
            best_idx = -1
            for i, det in enumerate(detections):
                if i in used:
                    continue
                iou = PersonDetector._iou(track.box, det)
                if iou > best_iou:
                    best_iou = iou
                    best_det = det
                    best_idx = i
            if best_iou > self.iou_th:
                track.box = best_det
                track.age = 0
                track.hits += 1
                matched[tid] = track.box
                used.add(best_idx)
            else:
                matched[tid] = track.box  # keep last

        # New tracks
        for i, det in enumerate(detections):
            if i not in used:
                tid = self.next_id
                self.tracks[tid] = Track(tid, det)
                self.next_id += 1
                matched[tid] = det

        return matched

    @staticmethod
    def _iou(a: Box, b: Box) -> float:
        x1 = max(a.x1, b.x1)
        y1 = max(a.y1, b.y1)
        x2 = min(a.x2, b.x2)
        y2 = min(a.y2, b.y2)
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        union = (a.w() * a.h()) + (b.w() * b.h()) - inter
        return inter / union if union > 0 else 0


def _get_head_region(person: Box) -> tuple[int, int, int, int]:
    """Get head region from person box (upper 40%)."""
    x1, y1, x2, y2 = person.xyxy()
    head_y2 = y1 + int((y2 - y1) * 0.4)
    return x1, y1, x2, head_y2


def _get_torso_region(person: Box) -> tuple[int, int, int, int]:
    """Get torso region from person box (middle section)."""
    x1, y1, x2, y2 = person.xyxy()
    torso_y1 = y1 + int((y2 - y1) * 0.3)
    torso_y2 = y1 + int((y2 - y1) * 0.8)
    return x1, torso_y1, x2, torso_y2


class PPEDetector:
    """ONNX 런타임을 사용한 PPE 감지기.

    YOLOv8/v12 계열 모델을 ONNX 형식으로 로드하여 CPU 추론을 수행한다.
    SRP: 이 클래스는 오직 AI 추론 책임만 담당하며 비즈니스 로직은 포함하지 않는다.
    """

    def __init__(
        self,
        onnx_path: str,
        conf_threshold: float = 0.50,
        nms_iou_threshold: float = 0.45,
        input_size: int = 640,
        person_weights: str | None = None,
        person_conf: float = 0.45,
    ) -> None:
        """PPEDetector 초기화.

        Args:
            onnx_path: ONNX 모델 파일 경로
            conf_threshold: 최소 감지 신뢰도 임계값
            nms_iou_threshold: NMS IoU 임계값
            input_size: 모델 입력 이미지 크기 (정사각형 변의 픽셀 수)
            person_weights: Person detection model path (Ultralytics .pt)
            person_conf: Person detection confidence threshold
        """
        self._conf_threshold = conf_threshold
        self._nms_iou_threshold = nms_iou_threshold
        self._input_size = input_size

        # Person detector
        self._person_detector = PersonDetector(weights=person_weights, conf=person_conf)

        # CPU 전용 추론 세션 생성
        self._session = ort.InferenceSession(
            onnx_path,
            providers=["CPUExecutionProvider"],
        )

        # 모델 입출력 메타데이터 캐싱
        self._input_name: str = self._session.get_inputs()[0].name
        self._output_name: str = self._session.get_outputs()[0].name

        # 모델에 내장된 클래스 이름 추출 (없으면 인덱스로 폴백)
        self._class_names: list[str] = self._load_class_names()

        logger.info(f"PPEDetector 초기화 완료 | 모델: {onnx_path} | 클래스: {self._class_names}")

    def _load_class_names(self) -> list[str]:
        """ONNX 모델 메타데이터에서 클래스 이름을 추출한다."""
        try:
            meta = self._session.get_modelmeta().custom_metadata_map
            if "names" in meta:
                import ast

                names_raw = meta["names"]
                # {0: 'helmet', 1: 'jacket'} 형식의 문자열 파싱
                parsed = ast.literal_eval(names_raw)
                if isinstance(parsed, dict):
                    return [parsed[i] for i in sorted(parsed.keys())]
                if isinstance(parsed, list):
                    return parsed
        except Exception as e:
            logger.warning(f"클래스 이름 추출 실패, 인덱스로 폴백: {e}")
        return []

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        """OpenCV BGR 프레임을 YOLO 모델 입력 형식으로 변환한다.

        변환 과정: BGR→RGB → 정사각형 리사이즈 → [0,1] 정규화 →
                   HWC→CHW → 배치 차원 추가 → float32
        """
        # BGR → RGB 변환
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # 모델 입력 크기로 리사이즈 (비율 무시, YOLO 표준 방식)
        resized = cv2.resize(rgb, (self._input_size, self._input_size))

        # 픽셀값 정규화: [0, 255] → [0.0, 1.0]
        normalized = resized.astype(np.float32) / 255.0

        # HWC → CHW 변환 후 배치 차원 추가: (H,W,C) → (1,C,H,W)
        transposed = np.transpose(normalized, (2, 0, 1))
        return np.expand_dims(transposed, axis=0)

    def _postprocess(
        self,
        output: np.ndarray,
        orig_h: int,
        orig_w: int,
    ) -> list[Detection]:
        """YOLO ONNX 출력을 파싱하여 감지 결과 목록을 반환한다.

        YOLO 출력 형식 (ultralytics 기준):
            shape: (1, num_classes+4, num_anchors)
            각 앵커: [cx, cy, w, h, cls0_conf, cls1_conf, ...]

        Returns:
            NMS 적용 후 원본 이미지 좌표계로 변환된 Detection 목록
        """
        # 배치 차원 제거: (1, C, N) → (C, N)
        pred = output[0]

        # (C, N) → (N, C): 각 행이 하나의 앵커
        pred = pred.T

        num_anchors = pred.shape[0]
        # 앞 4개: cx, cy, w, h; 나머지: 클래스별 신뢰도
        boxes_xywh = pred[:, :4]
        class_scores = pred[:, 4:]

        # 각 앵커의 최대 신뢰도 클래스 선택
        class_ids = np.argmax(class_scores, axis=1)
        confidences = class_scores[np.arange(num_anchors), class_ids]

        # 신뢰도 임계값 필터링
        mask = confidences >= self._conf_threshold
        if not np.any(mask):
            return []

        boxes_xywh = boxes_xywh[mask]
        confidences = confidences[mask]
        class_ids = class_ids[mask]

        # cx,cy,w,h (모델 입력 좌표계) → x1,y1,w,h (원본 이미지 좌표계)
        scale_x = orig_w / self._input_size
        scale_y = orig_h / self._input_size

        x1 = (boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2) * scale_x
        y1 = (boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2) * scale_y
        w = boxes_xywh[:, 2] * scale_x
        h = boxes_xywh[:, 3] * scale_y

        # OpenCV NMS 적용 (중복 박스 제거)
        boxes_list = [[float(x), float(y), float(bw), float(bh)] for x, y, bw, bh in zip(x1, y1, w, h)]
        conf_list = [float(c) for c in confidences]

        indices = cv2.dnn.NMSBoxes(
            boxes_list,
            conf_list,
            self._conf_threshold,
            self._nms_iou_threshold,
        )

        results: list[Detection] = []
        if len(indices) == 0:
            return results

        indices_array = cast(np.ndarray, indices)
        for idx in indices_array.flatten():
            bx, by, bw, bh = boxes_list[idx]
            x1_i = max(0, int(bx))
            y1_i = max(0, int(by))
            x2_i = min(orig_w, int(bx + bw))
            y2_i = min(orig_h, int(by + bh))

            cid = int(class_ids[idx])
            label = self._class_names[cid] if cid < len(self._class_names) else str(cid)

            results.append(
                Detection(
                    label=label,
                    confidence=float(confidences[idx]),
                    bbox=(x1_i, y1_i, x2_i, y2_i),
                )
            )

        return results

    def _associate_ppe_to_persons(self, persons: list[Box], ppe_detections: list[Detection], is_helmet: bool) -> list[Box]:
        """Associate PPE detections to persons based on anatomical regions."""
        keywords = _HELMET_KEYWORDS if is_helmet else _JACKET_KEYWORDS
        region_func = _get_head_region if is_helmet else _get_torso_region

        matched = []
        for person in persons:
            person_region = region_func(person)
            for det in ppe_detections:
                if _label_matches(det.label, keywords):
                    if self._iou(det.bbox, person_region) > 0.1:  # overlap threshold
                        matched.append(person)
                        break
        return matched

    @staticmethod
    def _iou(box1: tuple[int, int, int, int], box2: tuple[int, int, int, int]) -> float:
        """Calculate IoU between two boxes."""
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2

        xi1 = max(x1_1, x1_2)
        yi1 = max(y1_1, y1_2)
        xi2 = min(x2_1, x2_2)
        yi2 = min(y2_1, y2_2)

        inter_area = max(0, xi2 - xi1) * max(0, yi2 - yi1)
        box1_area = (x2_1 - x1_1) * (y2_1 - y1_1)
        box2_area = (x2_2 - x1_2) * (y2_2 - y1_2)
        union_area = box1_area + box2_area - inter_area

        return inter_area / union_area if union_area > 0 else 0

    def detect(self, frame: np.ndarray) -> ComplianceResult:
        """프레임에서 PPE 착용 여부를 감지한다.

        Args:
            frame: OpenCV BGR 형식의 입력 프레임

        Returns:
            ComplianceResult: 헬멧/조끼 착용 여부 및 감지된 객체 목록
        """
        orig_h, orig_w = frame.shape[:2]

        # Detect persons first
        persons = self._person_detector.detect(frame)
        if not persons:
            # No persons detected, no PPE compliance
            return ComplianceResult(
                has_helmet=False,
                has_jacket=False,
                detections=[],
            )

        # Detect PPE
        input_tensor = self._preprocess(frame)
        outputs = self._session.run([self._output_name], {self._input_name: input_tensor})
        ppe_detections = self._postprocess(cast(np.ndarray, outputs[0]), orig_h, orig_w)

        # Associate PPE with persons
        matched_helmets = self._associate_ppe_to_persons(persons, ppe_detections, is_helmet=True)
        matched_jackets = self._associate_ppe_to_persons(persons, ppe_detections, is_helmet=False)

        has_helmet = len(matched_helmets) > 0
        has_jacket = len(matched_jackets) > 0

        # Combine detections
        all_detections = ppe_detections
        for person in persons:
            all_detections.append(Detection(
                label='person',
                confidence=person.confidence,
                bbox=(person.x1, person.y1, person.x2, person.y2),
            ))

        return ComplianceResult(
            has_helmet=has_helmet,
            has_jacket=has_jacket,
            detections=all_detections,
        )

    def draw_boxes(
        self,
        frame: np.ndarray,
        result: ComplianceResult,
    ) -> np.ndarray:
        """감지 결과를 프레임에 시각화하여 반환한다.

        Args:
            frame: 원본 프레임 (수정되지 않도록 복사본 사용 권장)
            result: detect()가 반환한 ComplianceResult

        Returns:
            바운딩 박스와 레이블이 그려진 프레임
        """
        annotated = frame.copy()

        for det in result.detections:
            x1, y1, x2, y2 = det.bbox

            # 클래스에 따라 색상 선택
            if _label_matches(det.label, _HELMET_KEYWORDS) or _label_matches(det.label, _JACKET_KEYWORDS):
                color = _COLOR_ITEM
            elif result.is_compliant:
                color = _COLOR_COMPLIANT
            else:
                color = _COLOR_VIOLATION

            # 바운딩 박스 그리기
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            # 레이블 배경 및 텍스트
            label_text = f"{det.label} {det.confidence:.2f}"
            (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(
                annotated,
                label_text,
                (x1 + 2, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

        # 전체 화면 상단에 착용 상태 요약 표시
        status_text = "COMPLIANT" if result.is_compliant else "VIOLATION"
        status_color = _COLOR_COMPLIANT if result.is_compliant else _COLOR_VIOLATION
        cv2.putText(
            annotated,
            status_text,
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            status_color,
            2,
            cv2.LINE_AA,
        )

        return annotated
