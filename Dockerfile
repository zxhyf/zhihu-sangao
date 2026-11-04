# 智护三高 · 容器镜像
# 零第三方依赖，运行期只需要 Python 标准库
FROM python:3.12-slim

# 中文时区与编码：不设时区会让“今天/趋势”整体偏 8 小时
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 先拷代码（没有 requirements 需要安装，保持镜像极小）
COPY . /app

# 数据目录可在运行时挂卷覆盖
RUN mkdir -p /app/data /app/reports

# 容器里必须：对外开放 + 设访问密码 + 不自动开浏览器 + 用本地规则引擎
ENV APP_HOST=0.0.0.0 \
    APP_ENV=prod \
    JUDGE_MODE=1 \
    PREFER_LOCAL=1 \
    SEED_ON_FIRST_RUN=1 \
    APP_DATA_DIR=/app/data

EXPOSE 8600

# 说明：PORT 由平台注入时会自动覆盖（config.py 读取 PORT 环境变量）
CMD ["python", "app.py", "--no-browser", "--host", "0.0.0.0", "--port", "8600"]
