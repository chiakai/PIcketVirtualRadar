# PIcket Virtual Radar

以 Raspberry Pi 3 與 Adafruit 2.8 吋 PiTFT Plus 電容觸控螢幕，重新實作 Pocket Virtual Radar 的主要功能。這不是原始 ESP32 專案的直接移植，而是針對 Raspberry Pi OS Lite、320×240 橫向畫面、Linux 網路管理及設備長期運作重新設計的版本。

[English documentation](README_englisth.md)

## 專案目標與設計想法

- 開機後直接進入全螢幕雷達，不依賴桌面環境。
- 在 240×240 雷達區與 80 px 資訊欄內清楚呈現即時航機資訊。
- 使用 OpenSky OAuth2 API，但 API 或網路失敗時不終止畫面。
- 針對電容觸控設計簡單、可用手指操作的介面。
- 提供手機可用的 Web 設定頁，避免外接鍵盤。
- 無已知 Wi-Fi 時可建立設定熱點，具備失敗回復與實體按鍵重設。
- 使用 systemd、watchdog、原子設定寫入與 last-known-good 回復，適合長時間設備化運作。

## 硬體與作業系統

- Raspberry Pi 3
- [Adafruit PiTFT Plus 320×240 2.8" TFT + Capacitive Touchscreen，Product ID 2423](https://www.adafruit.com/product/2423)
- Raspberry Pi OS Lite 64-bit
- 螢幕解析度：320×240、RGB565
- 觸控控制器名稱：`EP0110M09`
- 橫向旋轉：預設 `rotate=90`，可由 Web 切換為 `270°`
- 背光：BCM GPIO 18、1 kHz PWM
- Wi-Fi 重設按鍵：BCM GPIO 17
- 安全關機按鍵：BCM GPIO 22
- Help 按鍵：BCM GPIO 27

PiTFT 電容版可能沒有 `/sys/class/backlight`，但仍可透過 GPIO 18 PWM 調整背光。預設亮度為 80%，Web 可設定 10–100%，每次調整 5%。

## 系統架構

```text
OpenSky OAuth2 / states API
            │
            ▼
     OpenSky 資料層 ── timeout／退避／最後成功資料
            │
            ▼
     ICAO24 航機追蹤 ── 插值／短期推算／過期移除
            │
            ▼
  320×240 Pygame renderer ── RGB565 ── /dev/fb0
            │
     ┌──────┴──────┐
 電容觸控       Web 設定頁
                    │
              NetworkManager
```

主要程式位於 `src/picket_virtual_radar/`：

- `app.py`：主迴圈、觸控操作與各元件協調。
- `radar_renderer.py`：雷達、資訊欄、overlay 與 QR Code。
- `opensky.py`：OAuth2 token、API 查詢、驗證、退避與快取。
- `tracking.py`：航機狀態、插值、推算及過期移除。
- `wifi_manager.py`：client 重連、AP fallback、SSID 掃描與按鍵重設。
- `web_server.py`：token 保護的 Web 設定介面。
- `settings_store.py`、`config_recovery.py`：原子寫入與設定回復。
- `system_health.py`：systemd watchdog、溫度、供電與安全關機。

## 開機行為

`picket-virtual-radar.service` 已設為開機啟動。正常流程如下：

```text
Raspberry Pi OS 啟動
→ PiTFT framebuffer／觸控載入
→ systemd 啟動雷達服務
→ 背光、觸控、Wi-Fi manager、Web 與 OpenSky 啟動
→ 全螢幕顯示雷達
```

網路或 OpenSky 不可用時，雷達畫面仍會啟動。服務採 `Type=notify`、30 秒 watchdog、`Restart=always`；程序無回應或正常退出後都會自動恢復。

## 螢幕配置

畫面分為左側 240×240 雷達區與右側 80×240 航機資訊欄。

### 雷達區

雷達圓顯示：

- 三層同心距離圓。
- 東、西、南、北與每 30° 方位刻度。
- 可關閉的綠色掃描線。
- 航機位置、Callsign 與依 heading 旋轉的方向符號。
- Web 可設定最多三個重點航班；命中時航機符號、方向圖示與 Callsign 改為紅色。
- 選取航機以青色圓圈標示。
- 經緯度投影會依緯度修正東西向距離。

雷達圓外的四角資訊：

- 左上：`PIcket RADAR`。
- 右上：右對齊的 `STATUS`，表示設備網路狀態。
- 左下：`WiFi` 與六段訊號格；有效格以亮綠色反白。Ethernet 真正取得 IPv4 與預設路由時改顯示 `Ethernet`。
- 右下：右對齊的 `RANGE` 與目前畫面半徑。

`STATUS` 可能顯示：

- `ONLINE`：Wi-Fi 或 Ethernet 可用。
- `AP`：Wi-Fi 設定熱點運作中。
- `CONNECTING`：正在切換 Wi-Fi。
- `DISCONNECTED`：尚未取得可用網路。

### Range 顯示縮放

在右下 Range 區域快速點兩下，可在完整顯示半徑與 50% 半徑間切換。例如設定 50 km 時，畫面會在 50 km／25 km 間切換。

這只改變雷達畫面投影與顯示的航機；OpenSky bounding box 與 API 查詢半徑仍以設定檔的 50 km 為準。縮放狀態不保存，服務重啟後恢復完整範圍。

### 右側 AIRCRAFT 資訊欄

右欄最上方顯示：

- `AIRCRAFT` 與目前畫面可見航機數。
- 選取航機的 Callsign 或 ICAO24。
- Heading。
- 高度及速度，單位依 Web 設定。
- 資料年齡。

資料年齡格式：

- `A:3s`：Actual，最後實際位置資料約 3 秒前取得。
- `P:12s`：Predicted，目前位置由最後速度與航向短期推算，來源資料約 12 秒前取得。

右欄最下方以單行顯示 OpenSky API 狀態：

- 綠色 `API OK`：更新成功。
- 黃色 `API CONFIG`：尚未設定 OAuth 憑證。
- 黃色 `API RATE`：OpenSky rate limit。
- 紅色 `API AUTH`：Client ID、Client Secret 或 token 驗證失敗。
- 紅色 `API ERROR`：網路、timeout、HTTP、JSON 或其他 API 錯誤。

`STATUS` 與 `API` 是不同狀態：網路正常但 token 錯誤時，右上仍是 `ONLINE`，右欄則顯示紅色 `API AUTH`。

## 觸控操作

- 點擊航機或 Callsign：選取航機並在右欄顯示詳細資料。
- 點擊雷達空白處：取消選取。
- 點擊右側資訊欄：依序切換 `Callsign → Details → Hidden`。
- 已選取航機時左右滑動：依距離循環切換航機。
- 雙擊 Range：在完整／50% 顯示半徑間切換。
- 長按雷達區：開啟 Quick Settings。
- 長按右側資訊欄：開啟 System / Settings 資訊頁。
- 點擊 overlay：關閉或操作該頁面。
- Help 頁開啟時上下滑動：捲動操作說明；Help 中的左右滑動與點擊不會操作雷達。

### Quick Settings

可直接切換：

- 掃描線。
- 航機 heading 符號。
- Callsign 顯示。
- 地面航機顯示；預設關閉。

### System / Settings 資訊頁

顯示：

- Hostname、IP。
- OpenSky API 狀態與航機數量。
- CPU 溫度。
- `PWR: OK`、即時供電／過熱警告或 `PWR: HISTORY`。
- Web URL 與 access token。
- 包含完整 Web URL 及 token 的 QR Code，可用手機直接掃描。

`PWR: HISTORY` 表示本次開機期間曾發生低電壓或節流，不代表現在仍在發生。即時低電壓、過熱或節流才會顯示在主要畫面。

### Help 頁

短按 Button 4／GPIO 27 可從雷達畫面開啟全螢幕 Help，再按一次回到雷達。Help 內容包括：

- 點擊、雙擊、長按與左右滑動等觸控操作。
- Quick Settings 與 System / Settings 的開啟方式。
- 四顆 PiTFT 實體按鈕的 GPIO、短按／長按功能。
- 紅色重點航班、青色選取圓圈、資料年齡、STATUS、API、Wi-Fi／Ethernet 的含義。
- Web 設定介面的 QR Code 入口。

一頁顯示 13 行；右上角顯示目前行數／總行數。向上滑看後續內容，向下滑回前面。每次開啟 Help 都從第一行開始。

## 實體按鍵

- PiTFT Button 1／GPIO 17：長按 8 秒，刪除已知 Wi-Fi client profiles 並建立 `PIcketRadar-Setup` 熱點。
- PiTFT Button 2／GPIO 22：長按 3 秒，透過 `systemctl poweroff` 安全關機。
- PiTFT Button 3／GPIO 23：目前未使用。
- PiTFT Button 4／GPIO 27：短按切換全螢幕 Help／雷達畫面。

設備控制需要安裝 `systemd/50-picket-device-control.rules`，以授權 `rpi` 建立 AP、切換 Wi-Fi 及安全關機。

關機按鈕刻意採長按操作以避免誤觸。GPIO 22 使用內部上拉，按下時為低電位；程式偵測到連續按下 3 秒後執行 `systemctl poweroff`。請勿改成 `loginctl poweroff`：Raspberry Pi OS 所附的 `loginctl` 可能不提供 `poweroff` command verb，journal 會顯示 `Unknown command verb 'poweroff'`。

GPIO 27 同樣使用內部上拉且按下為低電位。Help 在按鍵放開後切換一次，並有 50 ms debounce，避免一次按壓因接點彈跳重複開關。

## Web 設定介面

預設監聽所有介面的 TCP port 8080，並以隨機 access token 保護。使用系統資訊頁顯示的 URL／QR Code 進入：

```text
http://<Pi-IP>:8080/?token=<access-token>
```

成功驗證後瀏覽器會收到 HttpOnly、SameSite cookie。Web 使用 HTTP，應只在可信任的區域網路或設備設定 AP 中使用。

### Radar

- Latitude、Longitude：雷達中心點；預設桃園國際機場 `25.080278, 121.232222`。
- Radius：API 查詢與完整畫面的半徑。
- Distance unit：km 或 NM。

### OpenSky OAuth2

- Client ID。
- Client Secret；留白表示保留現有 Secret。
- Update interval：API 輪詢間隔，最小 10 秒。

### Display

- Callsign、Altitude、Speed。
- Radar scanline。
- Aircraft heading symbol。
- Highlighted flight 1–3：輸入最多三個要關注的 OpenSky Callsign；空白欄位不啟用。
- Rotation：下拉選擇 `90°` 或 `270°`；`270°` 相當於將目前方向旋轉 180°。
- Brightness：10–100%，每次 5%，透過 GPIO 18 PWM 套用。

重點航班採精確 Callsign 比對，但不分大小寫並忽略空白，例如輸入 `eva 123` 可匹配 `EVA123`。同一值重複輸入只保留一次；每個值最多 12 個 ASCII 字元，可使用英文字母、數字、`-` 與 `_`。全部留白即停用高亮。

OpenSky 提供的是航機 transponder 廣播的 Callsign，常使用 ICAO 航空公司代碼，不一定等於售票使用的 IATA 航班編號。例如長榮可能顯示 `EVA123`，而不是 `BR123`；應以雷達目前顯示的 Callsign 為準。命中的航機進入目前顯示範圍時，其航機符號、heading 圖示、雷達標籤及右側選取名稱會顯示紅色。

Rotation 同時影響 framebuffer 與電容觸控座標，不能只修改其中一項。旋轉值未變時，Save 後只重啟 radar；旋轉值改變時，系統會：

1. 透過受限的 `picket-display-rotate@90/270.service` 更新 PiTFT boot overlay。
2. 備份目前 boot config 為 `config.txt.pvr-rotation-backup`。
3. 將同一角度寫入 `touch.rotation`。
4. 回應 Web 請求後自動重新開機，通常約一分鐘可重新連線。

若 boot overlay 更新失敗，Web 會顯示錯誤且不儲存新角度；若設定檔寫入失敗，程式會嘗試將 boot 角度回復為原值。

### Localization

- Altitude unit：m／ft。
- Speed unit：kt／km/h。
- Timezone，例如 `Asia/Taipei`。

### Wi-Fi configuration

- 顯示目前 client／AP／Ethernet 狀態。
- 列出掃描到的 SSID、訊號與安全模式。
- 選擇 SSID 並輸入密碼。
- client Wi-Fi 密碼透過 `nmcli --ask` 的 stdin 傳送，不出現在程序參數或 log。
- 切換網路時目前的 Web 連線會中斷；成功後需使用新 IP 重新連線。
- 連線失敗時自動恢復設定 AP。

### Save 與設定回復

按下 `Save and restart radar` 後，畫面與 Web 約中斷 3–5 秒：

1. 完整驗證新設定。
2. 備份目前設定為 `config.json.last-known-good`。
3. 以暫存檔、`fsync` 與 `os.replace` 原子提交。
4. systemd 重新啟動服務。
5. 新設定正常運作 15 秒後移除 pending 標記。
6. 若新設定連續啟動失敗 3 次，自動還原 last-known-good。

## Wi-Fi AP fallback

正常開機會先使用 Raspberry Pi Imager 或 NetworkManager 保存的已知 Wi-Fi。無可用網路時：

1. 每 15 秒嘗試自動重連。
2. 45 秒仍失敗，建立 WPA2 設定熱點。
3. 螢幕顯示 SSID、密碼、`192.168.4.1`、Web URL 與 token。
4. 手機連線後開啟設定頁選擇新的 Wi-Fi。
5. client 連線失敗時恢復 AP。
6. AP 15 分鐘後嘗試已知 Wi-Fi，失敗則再次建立 AP。

預設值：

```text
SSID: PIcketRadar-Setup
Password: picket-radar
Gateway: 192.168.4.1
Web: http://192.168.4.1:8080/
```

Ethernet 只有在 carrier、NetworkManager connected、有效 IPv4 與 Ethernet default route 全部成立時才視為可用。

## OpenSky 資料與航機追蹤

- OAuth2 token 在到期前自動更新，Secret 不寫入 log。
- 使用中心點與設定半徑建立 latitude-aware bounding box。
- 驗證 HTTP status、JSON schema、空值與不合理位置。
- 排除缺少經緯度、超出設定半徑及預設的地面航機。
- HTTP timeout 預設 8 秒。
- poll interval 預設 15 秒。
- rate limit、認證及一般錯誤使用不同指數退避。
- API 失敗保留最後成功 snapshot，程式不會終止。
- ICAO24 為唯一識別碼。
- 新資料以預設 2 秒位置插值。
- 更新間隔內最多推算 20 秒。
- 預設 90 秒沒有資料後移除航機。

## 穩定性與設備管理

- 固定邏輯更新 10 Hz、畫面最高 30 FPS。
- `/dev/fb0` 全畫面 RGB565 或 dirty-rectangle 更新模式。
- SIGINT／SIGTERM 乾淨關閉 framebuffer、GPIO、觸控、Web 與背景執行緒。
- systemd 30 秒 watchdog；無回應時終止並在 3 秒後重啟。
- OpenSky 與 Wi-Fi 工作使用 timeout，外部失敗不阻塞主畫面。
- 溫度、即時／歷史低電壓與節流監控。
- journal 上限：persistent 50 MB、runtime 20 MB、單檔週期 7 天。
- 設定檔權限預設 `0600`，目錄 `0700`。

目前專案不採用 read-only root filesystem；Web 設定與 last-known-good 回復需要可寫入的持久設定目錄。

## 設定檔

正式設定：

```text
/etc/picket-virtual-radar/config.json
```

範例設定：[config.example.json](config.example.json)

重要區段：`display`、`runtime`、`radar`、`opensky`、`tracking`、`touch`、`ui`、`localization`、`web`、`wifi`。重點航班儲存在 `ui.highlight_callsigns`，格式為最多三個字串的 JSON array。

請勿將包含 OpenSky Client Secret、Web token 或 Wi-Fi 資訊的正式設定提交到版本控制。

## 安裝

安裝程式會保留既有 `/etc/picket-virtual-radar/config.json`：

```sh
cd ~/picket-virtual-radar
sudo ./install.sh
```

安裝設備控制 PolicyKit 權限：

```sh
sudo PVR_INSTALL_DEVICE_POLKIT=YES ./install.sh
```

安裝程式會：

- 安裝程式至 `/opt/picket-virtual-radar`。
- 建立使用系統 Python packages 的 virtual environment。
- 安裝並啟用 systemd service。
- 安裝 journald 限額與基本 PolicyKit 規則。
- 安裝受限制的螢幕旋轉 helper 與 templated systemd service。
- 依設定檔同步既有 `pitft28-capacitive` overlay 的 90°／270°，重新安裝時不會強制改回 90°。

設備控制 PolicyKit 規則只允許 `rpi` 啟動 `picket-display-rotate@90.service` 或 `picket-display-rotate@270.service`，以及執行必要的 reboot；任意角度、其他 systemd unit 或一般 root command 都不在授權範圍內。

### 更新已安裝的程式

服務實際載入 virtual environment 中的已安裝 package：

```text
/opt/picket-virtual-radar/.venv/lib/pythonX.Y/site-packages/picket_virtual_radar/
```

因此只修改 `/opt/picket-virtual-radar/src` 不會更新正在執行的程式。從專案目錄重新執行安裝程式，讓 source、virtual environment package、systemd 與 PolicyKit 規則保持一致：

```sh
sudo PVR_INSTALL_DEVICE_POLKIT=YES ./install.sh
```

可用以下指令確認服務真正載入的位置：

```sh
/opt/picket-virtual-radar/.venv/bin/python -c \
  'import picket_virtual_radar.system_health as m; print(m.__file__)'
```

## 維護指令

```sh
systemctl status picket-virtual-radar
journalctl -u picket-virtual-radar -f
sudo systemctl restart picket-virtual-radar
sudo systemctl stop picket-virtual-radar
```

安全查看不含 Secret 的設定摘要：

```sh
/opt/picket-virtual-radar/.venv/bin/python \
  /opt/picket-virtual-radar/tools/report_safe_config.py
```

## 開發與測試

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

目前測試涵蓋設定驗證、投影、OpenSky、追蹤、觸控、設定交易／回復、背光、Wi-Fi 與 Range 顯示縮放。

非破壞性設定中斷寫入測試：

```sh
/opt/picket-virtual-radar/.venv/bin/python \
  /opt/picket-virtual-radar/tools/test_config_power_loss.py
```

該工具在同一檔案系統的暫存目錄測試，不修改正式設定。

## 故障排除

### 畫面或 Web 在 Save 後消失

```sh
systemctl status picket-virtual-radar
journalctl -u picket-virtual-radar -n 100 --no-pager
```

服務使用 `Restart=always`，正常應在 3–5 秒恢復；連續失敗 3 次會還原 last-known-good。

### `API AUTH`

檢查 Client ID／Client Secret。程式會退避重試，不會退出。

### `API ERROR`

檢查 `STATUS`、DNS、系統時間與 OpenSky 服務。最後成功航機資料會暫時保留。

### `PWR: HISTORY`

表示本次開機曾發生低電壓或節流。建議使用穩定 5V／2.5A 以上電源及短而粗的電源線。

### 沒有背光調整

確認 PiTFT GPIO 18 backlight jumper、`gpio` 群組、`lgpio` 與服務 log。電容版沒有 `/sys/class/backlight` 是正常情況。

### GPIO 22 有偵測到，但沒有關機

先查看本次開機的完整紀錄，而不只是應用程式輸出：

```sh
sudo journalctl -b --since "5 minutes ago" --no-pager
```

依序確認：

1. 出現 `physical safe shutdown requested on GPIO 22`：按鍵接線、GPIO 權限與長按偵測正常。
2. 不應出現 `loginctl: Unknown command verb 'poweroff'`。若出現，代表服務仍載入舊 package；依「更新已安裝的程式」重新安裝。
3. 若出現 `safe shutdown command failed with exit code ...`：依同一行的 stderr 檢查 PolicyKit 或 systemd 權限。
4. 確認規則存在並已載入：

```sh
sudo test -f /etc/polkit-1/rules.d/50-picket-device-control.rules
sudo systemctl restart polkit.service
systemctl is-active polkit.service picket-virtual-radar.service
```

規則中的 `subject.user` 必須與 `picket-virtual-radar.service` 的 `User=` 相同；本專案預設皆為 `rpi`。`sudo` 不需密碼不代表 systemd service 可直接提權，因服務啟用了 `NoNewPrivileges=true`，設備操作應透過最小範圍的 PolicyKit 規則授權。
