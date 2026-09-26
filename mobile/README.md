# 찐맛 모바일 (Expo + expo-router)

```powershell
# 1) 백엔드 먼저 실행 (backend/README.md)
# 2) 앱
cd mobile
npm install
npx expo start          # Expo Go 앱으로 QR 스캔, 또는 a 키 = 안드로이드 에뮬레이터
npm run typecheck
```

- API 주소: 기본 `http://10.0.2.2:8000`(안드로이드 에뮬레이터). 실기기는 `mobile/.env`에
  `EXPO_PUBLIC_API_URL=http://<PC의 LAN IP>:8000` (PowerShell `ipconfig`로 확인), 백엔드는 `--host 0.0.0.0`으로 실행.
- PowerShell에서 `npx.ps1 ... 스크립트를 실행할 수 없으므로` 오류 → `npx.cmd expo start` 로 실행하거나
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 한 번 실행.
- Windows 방화벽이 8000 포트를 막으면 실기기에서 연결 실패 → 인바운드 허용.
- 화면: `app/` (index=조건선택, recommendations, restaurant/[id], review/[id], scoring). 스펙: `docs/design/screens.md`
