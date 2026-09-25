# 餐厅选择器

这是一个仅在本机运行的 FastAPI 应用。它把 `data/restaurants.json` 作为餐厅名单的唯一运行时数据源，提供名单管理、上海门店定位与地图、附近公交/地铁站、单人随机，以及按多人公共交通总耗时排序和多人随机。

## 安装与启动

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

必须在设置变量的同一个 PowerShell 窗口中启动，子进程才会继承配置。项目此前的本地验收过程曾暴露过一枚 JS 安全密钥；继续使用真实地图前，应在高德控制台更换该密钥，再按上述方式输入新值。

本地启动命令只有这一条：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/>。停止服务后如需清除当前 PowerShell 进程中的值：

```powershell
Remove-Item Env:AMAP_WEB_SERVICE_KEY, Env:AMAP_JS_API_KEY, Env:AMAP_JS_SECURITY_KEY -ErrorAction SilentlyContinue
```

## 餐厅数据与备份

`data/restaurants.json` 是唯一名单来源，程序不包含另一份固定名单，也不会从任何脚本重新导入或覆盖餐厅数据。网页刷新、增删改、定位和排名都会重新读取该文件，因此在编辑器中保存后无需重启服务。

直接编辑前可在项目内创建一个被 Git 忽略的备份：

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item -LiteralPath data\restaurants.json -Destination "backups\restaurants-$stamp.json"
```

每条记录必须是 JSON 对象，包含唯一的正整数 `id`、非空 `name`、`type` 和 `cuisine`。可选的大众点评链接必须是允许的 HTTPS 商户链接；定位字段由网页流程维护。程序读取时会校验整个文件，遇到无效 JSON、缺字段、重复 ID、无效坐标或无效定位状态会明确报错，并保留原文件不动。

网页写入采用同目录临时文件和原子替换。每次操作都基于当时读取的文件版本；若读取后文件又被手工保存，接口返回冲突而不会覆盖手工内容。出现冲突时请刷新页面，确认新内容后重新操作，不要反复提交旧表单。

网页显示用户输入时按文本处理，不执行其中的 HTML。店名会保留繁体字和外文原始拼写；同名不同分店允许各自拥有不同 ID。

## 使用流程

### 名单管理和单人随机

在“餐厅管理”中输入名称、类型和菜系新增；已有记录可编辑或删除。修改店名、地址或门店 POI 会清除已经失效的定位资料。单人随机始终从文件当前的全部餐厅中等概率生成 `1～N` 编号，并显示随机数、总数、名称和类型；空名单会明确提示。

大众点评链接目前只做格式校验和保存，不抓取页面，也不保证能从分享链接提取门店名。只粘贴链接时页面会要求补填名称。O-02 仍未解决：遇到不能识别的分享链接，请输入完整店名，再在候选中人工确认具体门店。

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
- 应用是本地 MVP，未部署。正式名单中的门店仍需逐家确认，不能把“有 16 家记录”等同于“16 家均已定位”。

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
