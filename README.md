# 餐厅选择器

这是一个仅在本机运行的 FastAPI 应用，提供名单管理、归档与标签、点评分享文字本地解析、上海门店定位与地图、附近公交/地铁站、单人随机，以及按多人公共交通总耗时排序和多人随机。

## Windows 发行包（普通用户）

按以下顺序使用：

1. 复制或解压**整个** `dist\ChooseRestaurant` 文件夹到任意位置。不要只复制 `ChooseRestaurant.exe`；同目录的 `_internal` 文件夹是程序的一部分，缺少它就不能运行。
2. 双击 `ChooseRestaurant.exe`。程序只监听 `127.0.0.1:8000`，确认本程序已经就绪后才自动打开浏览器。
3. 第一次启动会看到 V2 发行包自带的 17 家名单，其中包含第 17 家“青鹤谷”。若要改用自己的名单，在网页“本机数据与高德配置”区域选择自己的 `restaurants.json`，点击“验证、备份并导入”。导入会先完整校验，再备份旧名单并原子替换；无效文件不会覆盖当前名单。
4. 在同一区域填写高德 Web 服务 Key、JS API Key 和 JS 安全密钥并保存。页面只显示是否已配置，不回显凭据。此前暴露过的 JS 安全密钥必须先在高德控制台更换，不能继续用于最终验收或日常分发。
5. 正常使用后，关闭启动窗口或在窗口中按 `Ctrl+C`。服务随启动程序停止；此后 `http://127.0.0.1:8000/` 无法访问，再次使用须重新双击 exe。

如果端口 8000 已被其他程序占用，启动窗口会明确报错并等待确认，不会打开该端口上其他程序的网页。关闭占用端口的程序后再启动餐厅选择器。

发行模式唯一可写名单位于：

```text
%LOCALAPPDATA%\ChooseRestaurant\data\restaurants.json
```

网页“本机数据与高德配置”区域会显示准确路径，并可打开该目录。第一次没有此文件时，程序才从 V2 发布模板复制当前公开的 17 家一次；以后重启、替换或升级发行文件夹都不会覆盖它。V1 tag 的历史基线仍是 16 家，但 V2 的源码正式名单和首启模板均为 17 家。

发行模式的三个持久化位置是：

- 名单：`%LOCALAPPDATA%\ChooseRestaurant\data\restaurants.json`
- 导入备份：`%LOCALAPPDATA%\ChooseRestaurant\data\backups`
- 当前 Windows 用户加密的高德配置：`%LOCALAPPDATA%\ChooseRestaurant\config\amap-credentials.dat`

也可以在关闭程序后手工备份名单；替换文件前应保留一份副本。不要编辑加密凭据文件。

高德三项配置可直接在同一区域输入。发行模式使用 Windows DPAPI 绑定当前登录用户加密保存到 `%LOCALAPPDATA%\ChooseRestaurant\config\amap-credentials.dat`；状态接口和页面只显示是否已配置，不回显 Web 服务 Key 或 JS 安全密钥。JS API Key 仍只在地图运行时按既有方式提供给浏览器。无 Key 时名单管理、归档、标签和单人随机仍可用。

无 Key 时，地图、真实地点搜索、附近站点和公交路线会明确提示不可用，但名单管理和单人随机不受影响。凭据由当前 Windows 用户保护；把发行文件夹复制给其他用户或其他电脑不会附带这些凭据。

### Beta 验收状态

`v2.0.0-beta.1` 当前是待审查候选，不是已发布正式版。源码完整回归和同一台 Windows 上的无 Python/venv 隔离发行 smoke 已通过；当前 17 家模板候选尚未在朋友的另一台 Windows 电脑或干净 Windows VM 上验收。此前真实高德地图、上海门店搜索和两人公交路线证据来自模板仍为 16 家时构建的上一份发行包，不能冒充本次 17 家模板新包的直接实测。没有 Key 时仍可使用名单管理、归档、标签和单人随机。

## 源码安装与启动（开发者）

在 Windows PowerShell 中进入项目并安装依赖：

```powershell
Set-Location D:\PythonProjects\ChooseRestaurant
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

高德功能使用同一应用下的三个配置。不要把值写进源码、README、`.env`、命令历史或 Git；下面的输入不会回显，且只把值放进当前 PowerShell 进程的环境中：

```powershell
function Set-PrivateProcessEnv([string]$Name) {
    $secure = Read-Host "请输入 $Name" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        [Environment]::SetEnvironmentVariable(
            $Name,
            [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr),
            'Process'
        )
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

Set-PrivateProcessEnv AMAP_WEB_SERVICE_KEY
Set-PrivateProcessEnv AMAP_JS_API_KEY
Set-PrivateProcessEnv AMAP_JS_SECURITY_KEY
```

三个值分别是：

- `AMAP_WEB_SERVICE_KEY`：高德“Web 服务”Key，仅由后端调用地点搜索、周边搜索和公交规划。
- `AMAP_JS_API_KEY`：高德“Web端（JS API）”Key，由后端运行时配置接口交给地图加载器；不要硬编码在静态文件中。
- `AMAP_JS_SECURITY_KEY`：JS API 配套安全密钥，仅由后端安全代理 `/_AMapService` 使用；不会由应用配置接口返回给浏览器，也不应写入日志。

必须在设置变量的同一个 PowerShell 窗口中启动，子进程才会继承配置。项目此前的本地验收过程曾暴露过一枚 JS 安全密钥；用户已确认旧 Key/安全密钥在高德控制台停用或删除，并保留新 Key。该状态来自用户确认，不是项目对控制台状态的独立验证。

本地启动命令只有这一条：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/>。停止服务后如需清除当前 PowerShell 进程中的值：

```powershell
Remove-Item Env:AMAP_WEB_SERVICE_KEY, Env:AMAP_JS_API_KEY, Env:AMAP_JS_SECURITY_KEY -ErrorAction SilentlyContinue
```

## 源码餐厅数据与备份

源码模式的 `data/restaurants.json` 是唯一名单来源；发行模式则使用上文的 `%LOCALAPPDATA%` 文件。首启模板是只读初始化资源，不是第二份运行时名单。网页刷新、增删改、定位和排名都会重新读取当前模式的数据文件，因此在编辑器中保存后无需重启服务。

直接编辑前可在项目内创建一个被 Git 忽略的备份：

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item -LiteralPath data\restaurants.json -Destination "backups\restaurants-$stamp.json"
```

每条记录必须是 JSON 对象，包含唯一的正整数 `id`、非空 `name`、`type` 和 `detail`。可选的大众点评链接必须是允许的 HTTPS 商户链接；定位字段由网页流程维护。程序读取时会校验整个文件，遇到无效 JSON、缺字段、重复 ID、无效坐标或无效状态会明确报错，并保留原文件不动。

网页写入采用同目录临时文件和原子替换。每次操作都基于当时读取的文件版本；若读取后文件又被手工保存，接口返回冲突而不会覆盖手工内容。出现冲突时请刷新页面，确认新内容后重新操作，不要反复提交旧表单。

网页显示用户输入时按文本处理，不执行其中的 HTML。店名会保留繁体字和外文原始拼写；同名不同分店允许各自拥有不同 ID。

### 从 V2 回退到 V1

Git tag 只保护代码，不会自动恢复餐厅数据。当前经过核实的迁移前 V1 格式备份是：

```text
backups\restaurants-v1-pre-v2-20260926-204725.json
```

该文件有 17 家，SHA-256 为 `85A3A374B043D15FA2CB71CFB073C92365ECB14F51C4FAAF8D2F2885B725480A`。回退时应：

1. 停止服务，把当时正在使用的 V2 `restaurants.json` 另存为新的 V2 备份。
2. 检查 V2 期间新增或修改的餐厅；迁移前备份不包含这些后续变化，直接恢复会丢失它们。需要保留的内容应先人工导出或合并。
3. 在代码工作树已经安全保存、允许切换版本后，再回到 `v1.0.0` 代码。
4. 把上述迁移前备份复制为 V1 代码使用的 `data\restaurants.json`，并在启动前再次核对摘要和条数。

不能仅执行 Git tag 切换后继续使用 V2 数据。V1 虽可能读到额外字段，却不理解归档语义，会把 `archived` 餐厅当作普通餐厅，也不能正确管理 V2 标签；这属于静默语义错误。当前仓库的 V2 修改尚未提交，因此现在也不应直接切换 tag。

## 使用流程

### 名单管理和单人随机

在“餐厅管理”中输入名称、类型、菜系和可选标签新增；已有记录可编辑、归档、恢复或明确删除。修改店名、地址或门店 POI 会清除已经失效的定位资料。单人随机只从当前 `active` 餐厅中等概率生成 `1～N` 编号；档案不参与，活跃名单为空时会明确提示。

大众点评支持允许的 PC/手机商户 URL 和 App 整段分享文字的纯本地解析，可从唯一的 `【店铺全称】` 提供可编辑名称建议；不抓取页面，地址只作待确认线索。只粘贴 URL 时仍要求补填名称，具体分店继续由高德候选人工确认。未知短链、网页元数据读取和使用许可仍未解决。

### 上海门店定位、地图和附近交通

定位先按餐厅完整原名搜索上海门店，再有限尝试简繁变体、大小写或有辨识度的部分外文名称。唯一且可信的精确门店才会自动保存；多分店、模糊或资料不完整时只列候选，必须选择具体分店，或在地图指定坐标并填写地址。人工确认的位置不会被批量自动定位覆盖。

只有坐标有效且状态为“自动定位”或“人工确认”的餐厅才显示地图标记；点击标记可看名称、地址和来源。门店附近最多显示 5 个公交/地铁站，距离是近似直线距离。无候选、无站点、请求失败和配置缺失分别提示，不会编造地址或坐标。

### 多人公共交通排名和多人随机

至少输入两名参与者，并让每人从上海地点候选中确认出发位置。应用对每家位置可靠的餐厅选取每位参与者最快的有效公共交通方案，以总耗时升序排名；同分时依次比较最慢一人的耗时和餐厅 ID。结果显示餐厅名称、地址、地图位置、总耗时，以及每人的耗时和公交/地铁方案。

任何一人没有有效路线时，该餐厅会列在排除区，缺失耗时不会当成 0，也不会用直线距离替代。高德服务失败造成结果不完整时会明确提示。修改参与者输入，或从结果页更正餐厅位置，都会立即使旧路线、排名和多人随机资格失效；确认位置后重新排名即可。多人随机只从最近一次成功、未失效的完整排名等概率抽取。单人随机不受这些状态影响。

## 配置缺失与外部服务限制

- 三项高德配置全部缺失时，名单管理和单人随机仍可使用；地图、真实地点搜索、附近站点和公交规划会显示配置缺失。
- 只有 JS API 配置不完整时，地图会提示不可用；后端 Web 服务能力是否可用取决于 `AMAP_WEB_SERVICE_KEY`。
- 无公交路线时餐厅被排除，不产生伪造排名。
- 配额用尽、超时或高德返回失败时页面显示具体失败或结果不完整；应用不会降级为直线距离，也不会把错误写入餐厅文件。
- 应用是本地 MVP，未部署。正式名单中的门店仍需逐家确认，不能把“名单中已有记录”等同于“所有门店均已定位”。

## 检查

离线回归：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Python 和前端语法检查：

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests
node --check app\static\app.js
```

自动化测试使用临时 JSON 和合成高德响应，不会改写正式名单。真实高德能力需要有效配置、网络、配额和对应 Key 授权。

## Windows 构建

构建必须在 Windows 上进行。先安装开发及构建依赖，再执行 one-folder 构建脚本：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\scripts\build_windows.ps1
```

产物位于 `dist\ChooseRestaurant\`，其中 `ChooseRestaurant.exe` 与 `_internal` 必须一起分发。`build/` 和 `dist/` 已被 Git 忽略。可用以下命令在隔离临时 `%LOCALAPPDATA%` 和不含 Python/venv 的 PATH 下执行离线发行 smoke；脚本不会使用真实高德 Key：

```powershell
.\scripts\smoke_windows_package.ps1
```
