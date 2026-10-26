# 生活秩序設計｜2026–2027 課程報名

Python 3.12+。前台 `/`、管理員介面 `/admin`。本機可使用 SQLite；正式環境使用 PostgreSQL 與 Gunicorn。部署步驟、必要環境變數及舊資料遷移見 [DEPLOY.md](DEPLOY.md)。

## 開發

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

預設 `127.0.0.1:8000`。管理員密碼須由安全環境變數 `ADMIN_PASSWORD` 提供，至少12字元，不提供預設密碼。`DATA_DIR` 可覆寫本機 SQLite 目錄，預設 `.data/registrations.sqlite3`。資料庫、密碼、備份不可提交 Git。不要使用聊天中曾公開的密碼。

## 功能與一致性

- 民國115年11月起：實戰9梯、初階3梯、台韓進階1梯，合計13梯、142小時。
- 必填個資同意、獨立且不預選的肖像同意／不同意、全名電子簽署。保留簽署姓名、時間及當時告知全文；拒絕肖像授權不影響報名。
- 後台登入、名單搜尋、梯次／肖像篩選、狀態管理、CSV 匯出及簽署查閱。
- Email 去除頭尾空白並 `casefold()` 產生 `email_key`；資料庫部分唯一索引 `(course_id,email_key) WHERE status <> '已取消'` 保證同一信箱及梯次僅一筆有效報名。
- 寫入使用交易。唯一性衝突回傳409與繁體中文提示，包含取消後重報、舊報名重新啟用的衝突。SQLite 使用 `BEGIN IMMEDIATE` 與30秒鎖等待，PostgreSQL 由唯一索引仲裁並行交易。
- 啟動會以交易升級舊 SQLite schema。若已有重複有效報名，停止升級且不更動資料，必須先依遷移文件處理。

## 測試

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check public/app.js
node --check public/admin.js
```

預設使用獨立暫存 SQLite，PostgreSQL 遷移案例會明確跳過。欲完整驗證 PostgreSQL、Gunicorn 與正式安全設定，先建立專用 `life_order_test` 資料庫，透過安全環境設定提供 `TEST_DATABASE_URL`，再執行：

```sh
TEST_GUNICORN=1 TEST_PRODUCTION=1 .venv/bin/python -m unittest discover -s tests -v
```

**測試會清空專用測試庫內的報名紀錄，絕不可指向正式庫。** 連線名稱必須含 `life_order_test`。測試驗證8次並行僅1筆有效報名、同信箱不同梯次、重新啟用衝突、交易回滾、舊庫升級、明確備份與重複處理、SQLite→PostgreSQL 遷移、後台權限、跨站請求及安全設定缺漏時拒絕啟動。CI 會啟動 PostgreSQL 16 跑完整套件。

## 營運限制

目前是報名意願登記，尚未整合付款、通知信、容量候補或課程編輯；地點、每日時間與退費規則待補充。電子簽署是輸入姓名及紀錄快照，不含身分核驗或憑證式簽章。保存期限已列告知，但到期刪除、備份清除、權利請求及肖像撤回須另行執行，尚無自動化作業。

管理員登入工作階段保留於單一程序記憶體，8小時到期、重啟須重新登入。因此 Gunicorn 明確使用1 worker、8 threads；暫不支援多 worker 或水平擴展。正式備份／還原、Render 入口 HTTPS 與重啟保存仍須在實際部署後驗收。

## 報名表單瀏覽器測試

送出按鈕不因欄位未填或報名未開放而停用。點擊後列出各欄位的繁體中文錯誤提示及紅框，捲動並聚焦第一個錯誤欄位；修正輸入即更新提示。課程梯次、姓名、電話、Email、個資同意、肖像選擇與同名電子簽署全部通過後，且報名已開放，才呼叫 API。僅請求進行中暫停連點，失敗時保留輸入並可重試。後端驗證仍保留。

```sh
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
python -m unittest discover -s browser_tests -v
```

瀏覽器測試啟動獨立暫存 SQLite，不使用真實報名資料。可用 `CHROMIUM_PATH` 指定既有 Chromium；未指定時優先使用系統 `chromium`，否則使用 Playwright 安裝的版本。CI 同時執行後端與瀏覽器測試；Render Blueprint 設為 `checksPass` 後，仍須在 Render 同步此設定，且服務連接的分支通過檢查，才能觸發自動部署。
