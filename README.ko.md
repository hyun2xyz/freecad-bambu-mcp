# FreeCAD → Bambu Studio → Print MCP

검토 가능한 FreeCAD-to-Bambu 작업을 위한 이식형 Python 3.11+ MCP·CLI입니다. CAD 실행, 제한된 3MF 사전 점검, 사용자 검토, LAN 업로드, 상태·제어를 하나의 영속 작업 기록으로 묶습니다.

## 범위

- 별도 설치한 `neka-nat/freecad-mcp` 애드온의 localhost XML-RPC를 사용합니다. upstream revision은 `3da6db5f71a7b74d1b69d295d1ba89233ad622b5`로 고정합니다.
- Bambu Studio GUI 슬라이싱과 실제 미리보기 확인, 또는 명시한 machine/process/filament profile을 사용하는 CLI 슬라이싱.
- A1, A1 mini, P1P/P1S, X1C/X1E의 단일 plate 출력. AMS 매핑, 최신 상태 확인, pause/resume/stop을 지원합니다.
- 실험적인 LAN MQTT/FTPS 전송입니다. H2, cloud, FEM, 독점 클라이언트 인증서 추출은 범위 밖입니다.

FreeCAD 1.1.3 내보내기와 Bambu Studio 2.8.2 GUI 슬라이싱·사전 검사를 macOS에서 확인했습니다. **실제 프린터 출력은 아직 검증하지 않았습니다.** 자세한 근거는 [검증 기록](docs/verification.md)에 있습니다.

## 설치

```sh
git clone https://github.com/hyun2xyz/freecad-bambu-mcp.git
cd freecad-bambu-mcp
uv sync --frozen
cp examples/config.example.json config.local.json
```

루트의 config 파일을 쓸 때 `workspace`를 `.`으로 바꾸십시오. 자격 증명은 JSON, `.env`, 저장소에 넣지 말고 로컬 셸의 환경 변수로만 설정합니다.

```sh
uv run freecad-bambu-mcp --config config.local.json doctor
uv run freecad-bambu-mcp --config config.local.json capabilities
```

FreeCAD를 실행하고 고정한 애드온의 RPC 서버를 `127.0.0.1:9875`에서 켜야 합니다. Windows 실행 파일은 `.venv\Scripts\freecad-bambu-mcp.exe`입니다.

## CLI 순서

[공유용 스킬](skills/freecad-bambu/SKILL.md)을 설치한 뒤 “freecad-bambu로 가운데 10mm 구멍이 있는 80×40×4mm 판을 만들고, 첫 레이어 확인 후 설정된 A1에서 출력해 줘”처럼 요청하면 전체 단계를 이어서 진행합니다. 실제 확인과 기존 승인을 유지하며, 장치 정보가 없으면 해당 단계에서 이어갈 수 있게 저장합니다. 패키지 내부에는 LLM 호출이 없습니다. 도구 12개, 파일 기반 스크립트와 작업 재개로 반복 문맥을 줄입니다.

```text
prepare → attach JOB sliced.3mf → review JOB SHA256 --preview-checked --hardware-checked
print JOB SHA256 --start-authorized → status JOB --refresh
```

`preview`, `printer-status`, `control JOB pause|resume|stop --authorized`, `close JOB --operator-confirmed`도 사용할 수 있습니다. review는 artifact hash, hardware profile, printer target, preflight를 묶습니다. upload/start는 최대 한 번만 시도하며, 결과가 불명확하면 재전송하지 말고 상태를 확인합니다.

MCP 서버는 같은 엔진을 stdio로 제공합니다. `examples/mcp.json`은 로컬 절대 경로로 바꿔 쓰는 템플릿입니다.

## 보안과 운영자 경계

FreeCAD Python은 신뢰 코드이며 기본 비활성입니다. LAN TLS 검증은 유지됩니다. 운영자 소유 CA를 사용하거나 신뢰하는 LAN에서만 self-signed를 명시 설정하십시오. 패키지가 보안 설정을 자동 변경하지 않습니다.

## 개발

```sh
uv run pytest
```

테스트는 offline mock이며 하드웨어나 물리 출력의 증거가 아닙니다. [설치 안내](docs/setup.md), [조사 기록](docs/research.md), [외부 구성요소](THIRD_PARTY.md)를 참고하십시오.
