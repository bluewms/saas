# BlueWMS SaaS

Odoo 20 SaaS 管理端、租户扩展和本地开发环境。

| 目录 | 用途 |
| --- | --- |
| [saas-addons](saas-addons) | 管理端模块、Docker Compose 和验收文档。最初来自 [bluewms/saas-addons](https://github.com/bluewms/saas-addons)。 |
| [access-addons](access-addons) | 租户登录、权限和配额扩展。 |
| [oca-queue](oca-queue) | OCA 作业队列。 |
| [oca-web](oca-web) | 依赖锁指定的 OCA Web 源码快照。 |
| [oca-contract](oca-contract) | 合同模块和 Odoo 20 适配。 |
| [oca-server-auth](oca-server-auth) | 注册邮件验证和 Odoo 20 适配。 |

从仓库根目录启动本地环境。

```sh
./saas-addons/scripts/saas-dev.sh init
```

各目录保留原有许可证。依赖来源及提交见[依赖锁](saas-addons/dependencies.lock.json)。自助开通配置、端口和本地隔离环境见[开发环境说明](saas-addons/docs/dev-environment.md)。
