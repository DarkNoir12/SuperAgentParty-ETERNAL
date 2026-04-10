![image](static/source/cover.png)

<div align="center">
  <a href="./README_CN.md">
    <img src="https://img.shields.io/badge/简体中文-自述文档-00B4AB?style=for-the-badge&logo=markdown"/>
  </a>
  <a href="./README.md">
    <img src="https://img.shields.io/badge/English-Readme-0057D2?style=for-the-badge&logo=markdown"/>
  </a>
  <a href="./README_PT.md">
    <img src="https://img.shields.io/badge/Português-Readme-FF69B4?style=for-the-badge&logo=markdown"/>
  </a>
  <a href="./README_JA.md">
    <img src="https://img.shields.io/badge/日本語-Readme-FF69B4?style=for-the-badge&logo=markdown"/>
  </a>
</div>

####

<div align="center">
  <a href="https://www.agentparty.top/"><img src="https://img.shields.io/badge/官网-AgentParty-blueviolet?style=for-the-badge"/></a>
  <a href="https://www.agentparty.top/blog.html"><img src="https://img.shields.io/badge/官网博客-Blog-orange?style=for-the-badge&logo=rss&logoColor=white"/></a>
  <a href="https://space.bilibili.com/26978344"><img src="https://img.shields.io/badge/B站-观看教程-red?style=for-the-badge&logo=bilibili"/></a>
  <a href="https://www.youtube.com/@LLM-party"><img src="https://img.shields.io/badge/YouTube-订阅频道-FF0000?style=for-the-badge&logo=youtube"/></a>
  <a href="https://gcnij7egmcww.feishu.cn/wiki/DPRKwdetCiYBhPkPpXWcugujnRc"><img src="https://img.shields.io/badge/中文使用指南-飞书文档-00CDCD?style=for-the-badge&logo=docsdotrs"/></a>
  <a href="https://temporal-lantern-7e8.notion.site/super-agent-party-211b2b2cb6f180c899d1c27a98c4965d"><img src="https://img.shields.io/badge/English%20Usage%20Guide-Notion-000000?style=for-the-badge&logo=notion"/></a>
  <a href="#快速开始"><img src="https://img.shields.io/badge/快速开始-下载-0052CC?style=for-the-badge&logo=github"/></a>
  <a href="./README.md#quick-start"><img src="https://img.shields.io/badge/English%20Version-Download-0052CC?style=for-the-badge&logo=github"/></a>
</div>

## 简介

### 🚀 **一款拥有无限可能的AI桌面伴侣！**

#### VRM桌宠：支持上传自定义VRM模型、动作、3D场景，打造专属桌面伴侣
![image](doc/image/img-1/vrm.jpeg)

#### 任务中心：让你的AI智能体可以在后台执行任何高级任务，自动控制电脑帮你干活，支持 MCP 和 Agent Skills
![image](doc/image/img-1/task.jpeg)

#### 多角色群聊：支持酒馆角色卡，支持长期记忆，你可以同时和多个角色一起聊天！
![image](doc/image/img-1/group.jpeg)

#### 即时通讯机器人：支持一键部署到QQ、飞书、钉钉、Telegram、Discord、Slack
![image](doc/image/img-1/im.jpeg)

#### 直播机器人：支持一键部署到B站、YouTube、twitch，支持360度全景直播
![image](doc/image/img-1/yt.jpeg)

#### AI浏览器：让你的AI智能体拥有自己的浏览器，支持自动控制
![image](doc/image/img-1/browser.jpeg)

#### 扩展系统：支持安装扩展，和自己创造新的扩展，下图为galgame扩展，扩展均支持独立窗口或者侧边栏两种方式打开
![image](doc/image/img-1/ext.jpeg)

#### 开发者友好：开放openai API接口、MCP接口，可以将智能体对外转接
![image](doc/image/img-1/api.jpeg)

## 快速开始

### Windows整合包（推荐！免安装源码版本，支持一键同步到仓库最新版本，无需等待桌面版打包）

  👉 [国际用户点击下载](https://github.com/heshengtao/super-agent-party/releases/download/v0.3.9/super-agent-party-win-v0.3.9.7z)
  👉 [中国用户点击下载](https://modelscope.cn/models/ailm32442/super-agent-party-portable/resolve/master/v0.3.9/super-agent-party-win-v0.3.9.7z)

⭐注意！你可以双击`quick-update.bat`更新软件，也可以双击`quick-start.bat`启动软件。操作系统需要是**Windows 10/11、Windows Server 2025**或者后续版本！

### Windows桌面版安装

  👉 [国际用户点击下载](https://github.com/heshengtao/super-agent-party/releases/download/v0.3.9/Super-Agent-Party-Setup-0.3.9.exe)
  👉 [中国用户点击下载](https://modelscope.cn/models/ailm32442/super-agent-party-portable/resolve/master/v0.3.9/Super-Agent-Party-Setup-0.3.9.exe)

⭐注意！安装时选择仅为当前用户安装，否则启动时需要管理员权限。操作系统需要是**Windows 10/11、Windows Server 2025**或者后续版本！

### MacOS整合包（目前只支持M芯片，适合开发者，同样是免安装源码版本，支持一键同步到仓库最新版本，无需等待桌面版打包）

  👉 [国际用户点击下载](https://github.com/heshengtao/super-agent-party/releases/download/v0.3.9/super-agent-party-mac-v0.3.9.7z)
  👉 [中国用户点击下载](https://modelscope.cn/models/ailm32442/super-agent-party-portable/resolve/master/v0.3.9/super-agent-party-mac-v0.3.9.7z)

⭐注意！你可以在终端使用`quick-update.sh`更新软件，也可以在终端使用`quick-start.sh`启动软件。在使用前，记得给文件加权限！

#### 🚀 使用步骤

**1. 移除网络下载隔离（重要）**
下载并解压后，打开终端，输入以下命令（注意末尾有空格），然后将**解压后的文件夹**拖入终端窗口并按回车：
```shell
sudo xattr -rd com.apple.quarantine 
```
*(注意：`-rd` 参数会递归移除文件夹内所有组件的隔离属性，否则 Python 环境可能无法正常工作。)*

**2. 授予脚本执行权限**
在终端中进入文件夹并执行：
```shell
chmod +x quick-update.sh quick-start.sh
```

**3. 运行软件**
- **首次使用/更新：**建议先执行 `./quick-update.sh` 确保依赖同步到最新版本。
- **日常启动：**直接执行 `./quick-start.sh`。

### MacOS桌面版安装（目前只支持M芯片）

  👉 [国际用户点击下载](https://github.com/heshengtao/super-agent-party/releases/download/v0.3.9/Super-Agent-Party-0.3.9-Mac.dmg)
  👉 [中国用户点击下载](https://modelscope.cn/models/ailm32442/super-agent-party-portable/resolve/master/v0.3.9/Super-Agent-Party-0.3.9-Mac.dmg)

⭐注意！下载后将dmg文件的app文件拖入`/Applications`目录下，然后打开终端，执行以下命令并输入root密码，从而移除从网络下载附加的Quarantine属性：

  ```shell
  sudo xattr -dr com.apple.quarantine /Applications/Super-Agent-Party.app
  ```

### Linux桌面版安装

我们提供了两种主流的 Linux 安装包格式，方便你在不同场景下使用。

#### 1. 使用 `.AppImage` 安装

`.AppImage` 是一种无需安装、即开即用的 Linux 应用格式。适用于大多数 Linux 发行版。

  👉 [点击下载](https://github.com/heshengtao/super-agent-party/releases/download/v0.3.9/Super-Agent-Party-0.3.9-Linux.AppImage)

#### 2. 使用 `.deb` 包安装（适用于 Ubuntu / Debian 系统）

  👉 [点击下载](https://github.com/heshengtao/super-agent-party/releases/download/v0.3.9/Super-Agent-Party-0.3.9-Linux.deb)

### Docker部署（该版本桌宠只能通过浏览器查看）

- 两行命令安装本项目：
  ```shell
  docker pull ailm32442/super-agent-party:latest
  docker run -d -p 3456:3456 -v ./super-agent-data:/app/data ailm32442/super-agent-party:latest
  ```

- ⭐注意！`./super-agent-data`可以替换为任意本地文件夹，docker启动后，所有数据都将缓存到该本地文件夹，不会上传到任何地方。

- 开箱即用：访问http://localhost:3456/

### Docker Compose部署（该版本桌宠只能通过浏览器查看，会额外启动一个网关容器，用于登录管理）

- 安装本项目：

  ```shell
  git clone https://github.com/heshengtao/super-agent-party.git
  cd super-agent-party
  docker-compose up -d
  ```

- ⭐注意！初始用户名为`root`，初始密码为`pass`，首次登录后请修改密码。

- 开箱即用：访问http://localhost:3456/

- API key管理： 访问http://localhost:3456/token.html

### 与Docker版本配套的轻量版客户端，将你的Docker版本变成桌面端

👉 [SAP-lite-Windows-exe](https://github.com/heshengtao/desktop-for-sap/releases/download/v0.1.2/super-agent-party-lite-Setup-0.1.2.exe)

👉 [SAP-lite-MacOS-dmg](https://github.com/heshengtao/desktop-for-sap/releases/download/v0.1.2/super-agent-party-lite-0.1.2-Mac.dmg)

### 源码部署

  ```shell
  git clone https://github.com/heshengtao/super-agent-party.git
  cd super-agent-party
  uv sync
  npm install
  npm run dev
  ```

## 扩展

新增了全新的扩展系统，你可以在这里 [扩展列表](https://super-agent-party.github.io/plugins.html) 查看有哪些插件可用，你也可以直接在party中直接在【开发者】->【扩展】中查看和安装插件。你可以在[super-agent-party.github.io](https://github.com/super-agent-party/super-agent-party.github.io) 将你自己开发的扩展添加到官方扩展列表中！

### 已有扩展

| 名称                  | 作者               | 描述                                                                 | 仓库地址                                             |
|-----------------------|-------------------|--------------------------------------------------------------------|--------------------------------------------------|
| Super Agent Party Example | heshengtao         | Super Agent Party 的示例插件，用于演示插件架构和能力。                | https://github.com/heshengtao/sap-example          |
| Super Agent Party Example With NodeJS | heshengtao        | 带nodeJS环境的Super Agent Party 的示例插件 | https://github.com/heshengtao/sap-example-with-node        |
| Web Preview           | heshengtao         | 为 Super Agent Party 提供网页预览功能的插件。                        | https://github.com/heshengtao/sap-web-preview      |
| Story Adventure       | heshengtao  | 一款利用 AI 生成故事内容和选项的交互式故事冒险插件。                   | https://github.com/heshengtao/sap-story-adventure  |
| Live 2D      | heshengtao  | 一款live2d前端插件。                   | https://github.com/heshengtao/sap-live2d  |
| AI Editor      | heshengtao  | 一款AI编辑器插件。                   | https://github.com/heshengtao/sap-aieditor  |
| AI galgame      | heshengtao  | 一款AI galgame 插件。                   | https://github.com/heshengtao/sap-aigalgame  |
| AI tarot reader      | heshengtao  | 一款AI 塔罗牌插件。                   | https://github.com/heshengtao/sap-tarot  |
| AI sheet      | heshengtao  | 一款AI 表格插件。                   | https://github.com/heshengtao/sap-ai-sheet  |
| AI drawio      | heshengtao  | 一款AI drawio插件。                   | https://github.com/heshengtao/sap-ai-drawio  |
| AI mermaid      | heshengtao  | 一款AI mermaid编辑器插件                  | https://github.com/heshengtao/sap-ai-mermaid  |
| AI RSS reader      | heshengtao  | 一款AI RSS阅读器插件                  | https://github.com/heshengtao/sap-rss  |
| Remote      | heshengtao  | 一键将 Super Agent Party 暴露到公网             | https://github.com/heshengtao/sap-remote  |
| Code Server      | heshengtao  | 为 Super Agent Party 提供的 IDE 扩展插件           | https://github.com/heshengtao/sap-code-server  |
| CLI      | heshengtao  |  CLI扩展 for Super Agent Party           | https://github.com/heshengtao/sap-cli  |

## 硬件要求

- CPU：2核及以上
- 内存：2GB及以上

**因为所有的模型都是可选的，可以接入本地部署引擎，也可以全部使用云服务商的接口，所以硬件要求几乎没有。在2核2G的云服务器上测试docker版本可以正常运行** 

## 使用方法

- 桌面端：点击桌面端图标即可开箱即用。

- web端或docker端：启动后访问http://localhost:3456/

- API调用：开发者友好，完美兼容openai格式，可以流式输出，完全不影响原有API的反应速度，无需修改调用的代码：

  ```python
  from openai import OpenAI
  client = OpenAI(
    api_key="super-secret-key",
    base_url="http://localhost:3456/v1"
  )
  response = client.chat.completions.create(
    model="super-model",
    messages=[
        {"role": "user", "content": "什么是super agent party？"}
    ]
  )
  print(response.choices[0].message.content)
  ```

- MCP调用：启动后，在配置文件中写入以下内容，即可调用本地的mcp服务：

  ```json
  {
    "mcpServers": {
      "super-agent-party": {
        "url": "http://127.0.0.1:3456/mcp",
      }
    }
  }
  ```

## 功能

主要功能请移步以下文档查看：
  - 👉 [中文文档](https://gcnij7egmcww.feishu.cn/wiki/DPRKwdetCiYBhPkPpXWcugujnRc)
  - 👉 [英文文档](https://temporal-lantern-7e8.notion.site/super-agent-party-211b2b2cb6f180c899d1c27a98c4965d)
  - 👉 [日文文档](https://wiki.agentparty.top)

| 功能 | 详情 |
| --- | --- |
| 支持的模型服务商 | 支持常见的本地部署引擎接口和云服务商接口，如：openai/ollama/dify等 |
| 多模态模型融合 | 融合了角色扮演、推理、视觉、图像生成、语音识别、语音合成等多种类型的模型，可组合使用 |
| VRM桌宠机器人 | 高度可自定义，支持自定义头像、自定义动画、语音对话、对话打断。可透明推流到OBS等录屏软件，支持双向VMC协议！ |
| 通讯平台机器人 | 目前支持QQ、飞书、Telegram、Discord、Slack，后续会接入更多平台 |
| 直播机器人 | 目前支持B站、YouTube、twitch，后续会接入更多平台 |
| 播报员机器人 | 支持长文本播报、多声音播报、数字人视频播报、超长文本批量转语音（可下载），支持解析EPUB等常见电子书格式，后续会开发章节式转换 |
| 聊天界面 | 聊天界面支持A2UI、数学公式、mermaid图、HTML代码图形等前端渲染功能，支持图片下载或复制。支持胶囊模式和助手模式，便于收缩停靠聊天界面。结合桌面视觉和截图，无缝融入工作娱乐 |
| 角色扮演 | 支持上传、编辑、下载酒馆角色卡。支持不同角色配置不同的语音和头像。使用角色卡时支持多语音，长期记忆，非角色文本使用旁白语音，支持emoji和表情包 |
| 丰富的原生工具 | 工具调用支持异步执行，包括：网页搜索、知识库访问、智能家居控制、浏览器控制、沙箱环境代码执行、控制ComfyUI进行图像生成、Claude code操作文件系统 |
| 自定义工具接口 | 支持MCP、Skills、A2A、HTTP请求以及任意LLM接口作为主智能体的工具，用户可自由定制智能体的工具链 |
| 开放外部API | 开发者友好，开放兼容OpenAI和MCP的API，以及桌宠API |
| 扩展系统 | 你可以在 [扩展列表](https://super-agent-party.github.io/plugins.html) 查看有哪些插件可用，你也可以直接在Party中导航到【开发者】->【扩展】查看和安装插件。你可以在 [super-agent-party.github.io](https://github.com/super-agent-party/super-agent-party.github.io) 将你自己开发的扩展添加到官方扩展列表中！ |
| 存储空间 | 所有文件和数据都存放在用户本地数据文件夹，部署在NAS上时也可作为局域网内的个人图床或文件主机 |

## 免责声明：
本开源项目及其内容（以下简称“项目”）仅供参考，不构成任何明示或暗示的保证。项目贡献者不对项目的完整性、准确性、可靠性、适用性承担任何责任。任何依赖项目内容的行为均由用户自行承担风险。在任何情况下，项目贡献者都不应对因使用项目内容而导致的任何间接、特殊或附带损失或损害承担责任。

## 特别说明  
1. 本开源项目的部分功能（如Edge TTS语音合成、B站WebSocket弹幕监控等）依赖于第三方服务提供的公开接口或实验性功能。这些功能可能因第三方政策变更而随时失效。开发者不对其稳定性、合法性或持续性负责。使用本项目即视为用户已理解并同意承担相关风险。开发者不建议或鼓励将这些功能用于商业或大规模部署场景。

2. QQ机器人使用官方QQ机器人接口，请遵守 [AIGC QQ机器人使用规范](https://q.qq.com/#/news/detail?id=1376238e8e2fbbc036676bb09d2f37da)。

3. 本项目提供的浏览器控制功能是基于大语言模型（LLM）的无障碍辅助浏览界面，旨在帮助视力障碍人士、老年人或行动不便者通过自然语言命令更方便地操作浏览器，使用AI视觉识别技术。并非用于自动化爬取或黑客攻击。本项目采用“LLM视觉推理→单步操作”的技术架构，无障碍辅助浏览界面具有以下特点：  
   a. 非高频并发：由于依赖LLM推理速度（每步3-5秒）和内置的随机人类延迟算法，该工具的操作频率严格低于普通人类用户的最大手动操作速度。  
   b. 无服务器压力：该工具不支持多线程并发、批量数据抓取或DDoS攻击。从服务器角度来看，其行为与普通人类用户无异，不会对目标网站服务器造成额外负载。

4. 不要在银行、支付网关或高度机密信息页面使用本项目。开发者不对用户操作不当导致的隐私泄露负责。禁止行为包括：大规模数据抓取、绕过安全机制、网络干扰以及违法违规行为。

5. 本项目中出现的任何第三方商标、标识或品牌名称（包括但不限于OpenAI、Microsoft、Google、Bing、Bilibili等）均为其各自所有者的财产。这些标识仅用于方便用户识别所使用的模型或服务，并不暗示与这些权利人有任何官方关联、赞助或认可。若相关商标、接口或品牌所有者认为使用本项目不当，或不希望其品牌标识/接口通过本软件被展示或访问，请通过GitHub Issues或hst97@qq.com联系仓库管理员。我们将在收到通知后（通常在48小时内）根据要求删除、清除或修改相关内容。

6. 本项目是一款独立开发的开源工具。当用户使用本软件访问第三方API服务时，有责任遵守相关服务提供商的服务条款。

7. 本软件通过第三方大模型生成的任何内容，其准确性、完整性和合规性由模型提供商和用户行为负责。本软件作者对此类内容不承担法律责任。

## 许可证协议

本项目采用双许可证模式：
1. 默认情况下，本项目遵循 **GNU Affero 通用公共许可证 v3.0 (AGPLv3)** 许可证协议
2. 如需将本项目用于闭源商业用途，必须获得项目管理员的商业许可证。商务合作：hst97@qq.com

未经书面授权，将本项目用于闭源商业用途被视为违反本协议。AGPLv3的完整文本请参阅项目根目录下的LICENSE文件或 [gnu.org/licenses](https://www.gnu.org/licenses/agpl-3.0.html)。

### 第三方许可证声明  

本项目可能包含或依赖某些第三方库或组件，其许可证可能与主项目许可证不同。为遵守相关许可证要求，你可以在项目根目录下的 [LICENSE-third-party](./LICENSE-third-party) 文件夹中找到这些第三方组件的许可证信息，或在相应组件的源代码中查看。

我们向所有第三方库和组件的贡献者表示感谢，并承诺尊重他们的许可证条款。

## 支持：

### 请给我们点个star吧！
⭐你的支持是我们前进的动力！

<div align="center">
  <img src="doc/image/star.gif" width="400" alt="star">
</div>

### 关注我们
<div align="center">
  <a href="https://space.bilibili.com/26978344">
    <img src="doc/image/B.png" width="100" height="100" style="border-radius: 80%; overflow: hidden;" alt="bilibili"/>
  </a>
  <a href="https://www.youtube.com/@agentParty">
    <img src="doc/image/YT.png" width="100" height="100" style="border-radius: 80%; overflow: hidden;" alt="youtube"/>
  </a>
</div>

<div align="center">
  <a href="https://www.youtube.com/watch?v=fIzlQOsuhZE" target="_blank">
    <img src="https://img.youtube.com/vi/fIzlQOsuhZE/0.jpg" 
         width="600" 
         alt="YouTube Video Thumbnail"
         style="border-radius: 8px; border: 1px solid #eee;">
  </a>
</div>

### 加入社区
如果你有任何关于项目的问题或意见，欢迎加入我们的社区。

1. QQ群：`931057213`

<div style="display: flex; justify-content: center;">
    <img src="doc/image/Q群.jpg" style="width: 48%;" />
</div>

2. 微信群：`we_glm`（添加小助手微信并入群）

3. Discord: [Discord链接](https://discord.gg/f2dsAKKr2V)

## 贡献者  

<a href="https://github.com/heshengtao/super-agent-party/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=heshengtao/super-agent-party" />
</a>

## Star历史

[![Star History Chart](https://api.star-history.com/svg?repos=heshengtao/super-agent-party&type=Date)](https://www.star-history.com/#heshengtao/super-agent-party&Date)