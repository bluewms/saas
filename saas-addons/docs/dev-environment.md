# SaaS 本地开发环境

两端共用本机的 `odoo:20` 镜像，分别运行 Odoo 进程和 PostgreSQL `16.0`，各自持久化数据库和附件。仅在本机发布 Odoo HTTP 端口。

| 实例 | 登录地址 | 数据库 |
|---|---|---|
| 管理端 | [127.0.0.1:8072](http://127.0.0.1:8072/web/login) | `saas_master` |
| 客户端 | [localhost:8073](http://localhost:8073/web/login) | `saas_client` |

两个入口使用不同主机名，便于在同一个浏览器同时登录。两端初始开发账号均为 `admin`，密码为 `admin`。数据库连接密码和 Odoo 数据库管理密码由初始化脚本随机生成，保存在 `.saas-dev/.env`。

## 首次初始化

启动 Docker Desktop，并准备 [依赖锁](../dependencies.lock.json) 中的 ARM64 镜像。`SAAS_ODOO_IMAGE` 和 `SAAS_POSTGRES_IMAGE` 可指定其他本地镜像。OCA Queue 默认从同级 `../oca-queue` 加载，使用依赖锁记录的提交。Python 依赖由初始化脚本按锁定哈希安装，需要本机有 Python 3 和 pip。

```sh
cd /Users/jianglang/odoo/saas/saas-addons
./scripts/saas-dev.sh init
```

已有离线 wheel 时，可在首次初始化前设置 `PIP_NO_INDEX=1` 和 `PIP_FIND_LINKS`，后者指向 wheel 所在目录。OCA Queue 在其他目录时，启动前设置 `SAAS_QUEUE_ADDONS`。

若要保留日常开发环境并另外初始化一套空白数据库，请设置独立的 Compose 项目名和端口。后续操作该套环境时使用相同的环境变量。

```sh
COMPOSE_PROJECT_NAME=saas-lifecycle SAAS_DEV_MASTER_PORT=8172 SAAS_DEV_CLIENT_PORT=8173 \
  ./scripts/saas-dev.sh init
```

本地客户 Operator 的 **DB URLs** 要使用对应的客户端端口。

管理端安装 SaaS 核心、远程 Operator、门户、应用目录、域名、备份和额度等可用模块。备用客户库 `saas_client` 安装基础 Web 和 `saas_cluster_simple`。部署模板时，远程 Operator 将其所需的应用和客户插件安装到对应模板库。

## 客户模板依赖

客户端从同级 `../access-addons` 加载 `odoo20-client` 适配工作区，从 `../oca-web` 加载锁定的 OCA Web 20.0 源码。使用其他目录时可设置 `SAAS_ACCESS_ADDONS` 和 `SAAS_WEB_ADDONS`。具体来源和提交见 [依赖锁](../dependencies.lock.json)。

| 用途 | 模块 |
|---|---|
| 单点登录、应用权限和用户数 | `auth_quick`、`access_apps`、`access_limit_max_users` |
| 到期、容量和客户后台 | `database_expiration`、`database_limit_size`、`web_responsive` |
| 上述客户功能的间接依赖 | `access_restricted`、`ir_rule_protected`、`access_limit_records_number`、`database_block`，以及 Odoo 自带 `base_automation`、`web_tour` 和 `mail` |
| 网站注册与付款开通 | 管理端的 `saas_apps_signup` 和 `saas_contract`，以及 `../oca-server-auth` 和 `../oca-contract` 中已适配的 OCA 模块 |

本地远程 Operator 使用 Docker 服务地址 `http://client:8069`。模板库安装作业失败后，补齐依赖并重启客户端，再在管理端重新排队原安装作业即可复用已建好的模板库。

## 本地租户入口

将本地客户 Operator 的 **DB URLs** 设为 `http://{db_name}.localhost:8073`。为要登录的构建添加同名本地域名，例如给 `testa` 分配 `testa.localhost`。域名记录只填写主机名。保存后，队列会把映射写进客户 Odoo 的持久卷，重启后可继续使用。

在就绪构建中点击 **连接到构建**，依次确认管理端授权和客户库登录。默认客户库仍使用 `http://localhost:8073`。单点登录的服务器间令牌验证使用管理端 Docker 地址 `http://master:8069`。

恢复库可以绑定一个独立的本地域名，例如 `testa-restored.localhost`。登录会使用构建已绑定的域名，并沿用 Operator URL 的协议和端口。验收时可用源库的一条 CRM 记录和一个附件逐项比对。

## 自助注册与付款测试

准备 [依赖锁](../dependencies.lock.json) 指定的 OCA 本地提交，并在独立数据卷上启用自助开通配置。

```sh
export SAAS_DEV_COMMERCE=1 COMPOSE_PROJECT_NAME=saas-commerce
export SAAS_DEV_MASTER_PORT=8272 SAAS_DEV_CLIENT_PORT=8273
./scripts/saas-dev.sh init
```

该环境的管理端在 `http://127.0.0.1:8272`，客户侧在 `http://localhost:8273`。为技术模板 `Base` 在远程客户 Operator 上添加部署，等待「就绪」，再配置要售卖的应用或套餐。开发测试使用仅在 Docker 内网监听的邮件捕获器。邮箱令牌确认成功后，才建立客户公司并提交试用建库或绑定已验证的购物车。

在 SaaS 设置中启用应用或套餐显示及试用按钮，即可从 [网站选品页](http://127.0.0.1:8272/price) 开始。客户选择产品后点击首月免费，输入子域名并验证邮箱。系统会创建试用合同，自动开通租户并绑定该子域名。租户就绪后，客户可从门户的 **My Builds** 进入工作区。免费期从邮箱确认起计一个日历月，期间不会开出续期发票。

付款验收使用独立账套。配置测试会计科目、收款日记账和销售自动开票。实际入账后核对租户、合同及已应用标记。重复处理同一笔已付发票时，租户开通和续期各只生效一次。

## 日常启动与停止

```sh
./scripts/saas-dev.sh up -d --wait
./scripts/saas-dev.sh ps
./scripts/saas-dev.sh logs -f master client
./scripts/saas-dev.sh stop
```

停止后数据库和附件保留在 Docker 卷中。源码以只读方式挂载到容器，可在仓库中编辑。修改 Python 后重启对应服务。需要更新数据库中的模块结构或视图时，例如更新管理端 `saas` 模块，使用以下命令。

```sh
./scripts/saas-dev.sh stop master
./scripts/saas-dev.sh run --rm master --update=saas --stop-after-init
./scripts/saas-dev.sh up -d --wait master
```
