"""
Video source management router.
Allows switching between RTSP stream and uploaded video file.
"""

import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from backend.models.schemas import RtspSourceRequest, SourceStatusResponse, WebcamSourceRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/source/status", response_model=SourceStatusResponse)
async def get_source_status(request: Request):
    """현재 영상 소스 상태를 반환한다."""
    detection_loop = request.app.state.detection_loop
    status = detection_loop.source_status
    return SourceStatusResponse(**status)


@router.post("/source/rtsp")
async def set_rtsp_source(request: Request, body: RtspSourceRequest):
    """RTSP 스트림으로 영상 소스를 변경한다.

    요청 예시:
        POST /api/source/rtsp
        {"url": "rtsp://192.168.1.100:554/stream"}
    """
    detection_loop = request.app.state.detection_loop
    url = body.url.strip()

    if not url:
        raise HTTPException(status_code=400, detail="RTSP URL이 비어 있습니다.")
    if not url.startswith("rtsp://"):
        raise HTTPException(status_code=400, detail="올바른 RTSP URL이 아닙니다. (rtsp://로 시작해야 합니다)")

    detection_loop.set_source_rtsp(url)
    logger.info(f"RTSP 소스 변경 요청: {url}")

    return JSONResponse({"message": f"RTSP 소스 변경됨: {url}"})


@router.post("/source/webcam")
async def set_webcam_source(request: Request, body: WebcamSourceRequest):
    """연결된 웹캠으로 영상 소스를 변경한다.

    요청 예시:
        POST /api/source/webcam
        {"device_id": 0}
    """
    detection_loop = request.app.state.detection_loop
    detection_loop.set_source_webcam(body.device_id)
    logger.info(f"웹캠 소스 변경 요청: device_id={body.device_id}")
    return JSONResponse({"message": f"웹캠 소스 변경됨: device_id={body.device_id}"})


@router.post("/source/file")
async def set_file_source(
    request: Request,
    file: UploadFile = File(..., description="분석할 영상 파일"),
    start_timestamp: str = Form(
        ...,
        description="영상 녹화 시작 시각 (ISO8601, 예: 2025-03-18T09:00:00)",
    ),
):
    """업로드된 영상 파일로 소스를 변경한다.

    start_timestamp는 영상 내 각 프레임의 실제 촬영 시각을 계산하는 데 사용된다.
    예: 영상이 09:00:00에 녹화 시작됐고 10fps라면, 100번째 프레임 = 09:00:10

    요청 형식: multipart/form-data
        - file: 영상 파일
        - start_timestamp: ISO8601 문자열
    """
    # 시작 타임스탬프 파싱
    try:
        parsed_ts = datetime.fromisoformat(start_timestamp)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_timestamp 형식 오류. ISO8601 형식이어야 합니다. (예: 2025-03-18T09:00:00)")

    # 업로드 파일을 임시 디렉터리에 저장
    suffix = Path(file.filename or "video").suffix or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    detection_loop = request.app.state.detection_loop
    detection_loop.set_source_file(tmp_path, parsed_ts)

    logger.info(f"파일 소스 변경: {file.filename} (시작: {parsed_ts.isoformat()})")

    return JSONResponse(
        {
            "message": f"파일 소스 변경됨: {file.filename}",
            "start_timestamp": parsed_ts.isoformat(),
        }
    )
