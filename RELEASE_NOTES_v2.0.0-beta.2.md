# ChooseRestaurant v2.0.0-beta.2

这是供朋友目标机验收的 Windows Beta 候选，不是最终稳定版。

本 beta.2 在撤下 beta.1 后重新发布：GitHub 源码历史已移除仅供本地开发使用的 references 文档；Windows 程序包内容未改变。

## 下载与启动

1. 下载并解压 `ChooseRestaurant-v2.0.0-beta.2-win64.zip`。
2. 保留完整的 `ChooseRestaurant` 文件夹；`ChooseRestaurant.exe` 和 `_internal` 缺一不可。
3. 双击 `ChooseRestaurant.exe`。程序仅监听本机 `127.0.0.1:8000`，就绪后自动打开浏览器；关闭启动窗口后服务停止。
4. 首次启动会初始化公开的 17 家餐厅名单。已有 `%LOCALAPPDATA%\ChooseRestaurant\data\restaurants.json` 时，启动或替换程序包都不会覆盖它。
5. 高德配置可在网页“本机数据与高德配置”中保存。无 Key 时，名单管理、归档、标签和单人随机仍可使用；地图、地点搜索、附近站点与公交排名会明确提示不可用。

## 本 Beta 的功能

- 保留 V1 的 JSON/网页 CRUD、原子写入与冲突保护、上海门店定位、地图与附近站点、单人随机、多人公交总秒数排名与多人随机。
- 新增餐厅归档/恢复；只有活跃餐厅进入随机和多人排名。
- 新增任意中文、繁体及外文标签。
- 新增大众点评 PC 链接、移动 `/shopinfo/` 链接和 App 完整分享文本的本地解析与预览。
- 新增 Windows one-folder 双击启动、用户数据导入/备份和 Windows 用户级加密配置。

## 已知限制与验收状态

- 尚未在朋友的另一台 Windows 10/11 电脑或干净 Windows VM 完成目标机验收，因此仍为 Beta。
- 新的 17 家模板包已通过同一台 Windows 11 上、项目外目录且 PATH 不含 Python/venv 的隔离 smoke；这不等同于独立目标机验收。
- 此前真实高德地图、搜索和公交复核针对的是首启模板仍为 16 家的上一份发行包，不能视为本候选包的直接真实服务测试。
- 不抓取大众点评网页、不跟随未知短链，也不保证从任意分享链接自动得到店名；失败时可手工填写完整店名并用高德候选确认。
- 用户确认此前暴露的旧 JS Key/安全密钥已在高德控制台停用或删除，新 Key 继续保留；这是用户确认，不是本项目对控制台状态的独立验证。发行包不包含真实高德凭据。

## 候选校验

- ZIP：`ChooseRestaurant-v2.0.0-beta.2-win64.zip`
- SHA-256：`D8D070E0F6D502AB3B2D968BEF75FA30F2EC7CDD386FE08D4C5574A96B211E4B`
- 自动化测试：77/77 通过
- 首启模板：17 家，SHA-256 `85A3A374B043D15FA2CB71CFB073C92365ECB14F51C4FAAF8D2F2885B725480A`
