当前分支面向 Odoo 20。检查结论、已修复问题、生产部署缺口、登录客户端配套变更和升级步骤见 [SaaS 检查与改进记录](docs/saas-review.md)，外部依赖提交与可用状态见 [dependencies.lock.json](dependencies.lock.json)。

运行管理服务前设置服务器环境变量 `SAAS_MASTER_DATABASE` 为实际管理数据库名。客户登录插件需在令牌验证请求中发送其服务器端保存的 `auth_quick.build` 引用。完整 SaaS 仍需要对应的 Odoo 20 合同、邮箱验证和客户插件，管理端回归通过不能替代完整开通与恢复演练。

本地开发使用 [SaaS 双实例环境](docs/dev-environment.md)，分别登录管理端和客户库。

# SaaS addons

System to sale and manage odoo databases.

The repository contains modules for master instance (old name: *SaaS Portal*). Other resources of the project:

* https://saas.it-projects.info -- main website
* https://gitlab.com/itpp/saas-clusters -- modules for multi-server deployment
* https://github.com/itpp-labs/access-addons -- useful modules for client instances (*SaaS Client*)
* https://github.com/it-projects-llc/odoo-saas-tools -- abandoned original repository
