# Render 正式部署與資料遷移

本版已準備 PostgreSQL 部署設定；不代表已在 Render 套用。Blueprint 建立付費 Starter Web Service 及付費 PostgreSQL basic-256mb（新加坡、PostgreSQL 16），請先確認當期價格。程式碼位於修正分支，請經 PR 審查合併後再部署。若已在使用舊版 SQLite 永久磁碟，**先備份並遷移驗證，再切換服務；不要先刪除磁碟或套用會移除磁碟的設定。**

## Build / Start

- Build Command：`pip install -r requirements.txt`
- Start Command：`gunicorn --bind 0.0.0.0:$PORT --workers 1 --worker-class gthread --threads 8 --timeout 30 wsgi:application`
- Health Check：`/api/public`（會實際讀取資料庫設定）
- 公開 HTTPS 由 Render 提供；正式環境拒絕使用 `python server.py`。這個指令只供本機開發。

## 必要環境變數

| 名稱 | 設定與用途 |
|---|---|
| `APP_ENV` | 正式必須為 `production`，Blueprint 已設定 |
| `DATABASE_URL` | Render 由 `life-order-db` 注入內部 PostgreSQL 連線；屬機密，不得寫入 Git、聊天或日誌 |
| `ADMIN_PASSWORD` | 在 Render 安全欄位輸入全新至少12字元密碼；無預設值 |
| `PUBLIC_ORIGIN` | 在 Render 填實際 HTTPS 網址的 origin，例如 `https://你實際服務名稱.onrender.com`，不含路徑；自訂網域時須同步修改 |
| `COOKIE_SECURE` | 正式固定 `1`，管理員 Cookie 加上 Secure、HttpOnly、SameSite=Strict |
| `PORT` | Render 自動提供，Gunicorn 綁定此 port |
| `ORGANIZER` | Blueprint 已填共同主辦單位，僅初始化新資料庫 |
| `PRIVACY_EMAIL` | 已填 `orderdesigner2026@gmail.com`，僅初始化新資料庫 |
| `DATA_RETENTION` | 已填所報名梯次最後一日結束後一年，僅初始化新資料庫 |
| `PYTHON_VERSION` | Blueprint 指定3.12.12 |

`production` 啟動會檢查 PostgreSQL URL、密碼長度、安全 Cookie 與 HTTPS origin；缺一即拒絕啟動。沒有 PostgreSQL 連線時不會回退到 SQLite，也不會將報名資料寫入 Render 暫存檔案系統。Render PostgreSQL 設定 `ipAllowList: []`，預設只允許同帳號內部服務連線，不公開資料庫。

`ADMIN_PASSWORD` 和 `DATABASE_URL` 都只從環境讀取。不要使用代理佔位密碼，管理員驗證需要實際的安全 runtime 環境變數值。`DATA_DIR` 僅供本機 SQLite，正式 PostgreSQL 不使用。

## 首次部署（沒有既有報名）

1. 在 Render New → Blueprint 連接本儲存庫，選經審查的分支／main；確認付費資料庫與服務。
2. 填入 `ADMIN_PASSWORD` 與 `PUBLIC_ORIGIN`。若第一次建立時尚不知道最終網址，先讓服務保持啟動失敗，取得 Render 分配的網址後更新 `PUBLIC_ORIGIN` 並重新部署；不可移除安全檢查。
3. 等待 Build、資料庫及健康檢查通過。開啟實際 HTTPS 首頁及 `/admin`。
4. 登入後確認共同主辦單位、個資聯絡信箱、保存期限及肖像告知。新庫預設關閉報名。
5. 補齊正式課務資訊後開放報名，以管理者控制的測試信箱驗收拒絕肖像仍可報名、後台查閱、CSV 匯出及同信箱重複提示，測試資料標為已取消。
6. 重新啟動服務後，確認設定、紀錄仍存在；登出後所有後台 API 應回401。驗收後再分享公開網址。

## 舊 SQLite 升級與重複紀錄

先關閉報名並停止所有舊服務寫入，在可信任管理環境取得一致性 SQLite 備份。備份包含個資，須限制存取及保存。以下路徑為示意，請使用實際安全路徑；`--backup` 指定尚不存在的檔案，工具不會覆蓋舊備份。

```sh
python scripts/resolve_duplicates.py --source /secure/registrations.sqlite3
```

預設只回報重複組數，不改資料。如果有重複，由管理者先確認保留規則，再明確執行：

```sh
python scripts/resolve_duplicates.py --source /secure/registrations.sqlite3 --backup /secure/before-resolve.sqlite3 --apply
```

每組保留 `created,id` 排序最早的一筆有效，其餘改為已取消；不刪任何報名、簽署或告知快照。`duplicate_resolution_audit` 保存原狀態、處理時間及原因。工具先備份，再以交易改狀態；請先停寫，備份才對應維護時點。取消狀態不等於已聯絡學員，須由管理者確認後續課務。

## SQLite → PostgreSQL

1. 關閉報名、停止來源寫入，保留原庫與一致性備份。不要把 `.data` 或備份推送 Git。
2. 建立空的 PostgreSQL 目標庫；在 Render 同一內部網路的服務 Shell／可信任管理工作中，安全設定 `DATABASE_URL`，不要把 DSN 貼在命令列或聊天。不為遷移任意公開資料庫。
3. 確認已安裝 `requirements.txt`，先執行乾跑：

```sh
python scripts/migrate_sqlite_to_postgres.py --source /secure/registrations.sqlite3
```

4. 乾跑驗證來源格式與重複紀錄，僅列筆數，不測試遠端連線或寫入。確認後執行：

```sh
python scripts/migrate_sqlite_to_postgres.py --source /secure/registrations.sqlite3 --backup /secure/before-migrate.sqlite3 --apply
```

5. 工具保留全部報名 ID、時間、狀態、簽署快照、主辦設定及重複處理稽核；建立正規化 email key。來源保持不變；目標若已有報名會拒絕覆蓋。複製與筆數核對在單一 PostgreSQL 交易中完成，失敗整筆回滾，schema 初始化可能已完成。遷移後報名強制關閉，待驗收才開放。
6. 將 Web Service 切換到目標 PostgreSQL 與新版程式，確認筆數、授權與 CSV、登入及重啟保存。確認備份可還原後再考慮移除舊磁碟；移除前仍需保留合規備份。
7. 若失敗，維持維護狀態，不要讓新舊庫同時接收報名。切回原服務前確認舊庫未失去切換後新增紀錄；不要盲目回復舊備份。

## 待正式環境驗收

- Render 真實 Build／Start、HTTPS、`PUBLIC_ORIGIN` 及 Secure Cookie。
- 真實資料庫遷移（如有）、服務重啟後資料保留。
- 備份／還原演練、保存期限清除及權利請求流程。
- 資料庫區域為新加坡，已反映在個資告知；改區域須同步調整告知。

僅使用1個 Gunicorn worker，登入階段及限流尚未共用到 Redis 或資料庫，不支援多 worker／水平擴展。`autoDeployTrigger: off` 避免未經操作直接發布；PR 合併不會自動部署。
