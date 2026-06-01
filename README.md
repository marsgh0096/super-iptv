# Super IPTV Scan Service

北京联通 IPTV 组播公网 udpxy 动态扫源与自动保活服务。

## 💡 功能设计
*   **全自动扫源**：利用 ZoomEye 的免费开发者 API Key，定时在云端扫描公网中北京联通所有暴露且自定义端口的 `udpxy` 服务实例。
*   **多线程并发测活**：在云端通过并发拉取视频流与状态页面，测出丢包最低、连接数最少（最空闲）的健康节点。
*   **自动保活与刷新**：每 2 小时定时重新调度，将最新的保活 `.m3u` 直连列表自动更新发布，完全零本地开销。

## ⚙️ 部署说明
1.  进入本仓库的 `Settings` -> `Secrets and variables` -> `Actions`。
2.  点击 `New repository secret` 创建一个密钥。
3.  Name 填写 **`ZOOMEYE_KEY`**，Value 填写您的 ZoomEye 开发者 API Key。
4.  保存后，进入 `Actions` 选项卡，手动触发一次 `Run workflow` 即可生成第一个可播放的 `playlist.m3u` 订阅文件。
