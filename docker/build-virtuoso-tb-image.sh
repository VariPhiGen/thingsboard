#!/usr/bin/env bash
# Build virtuosonetsoft/tb-node:latest with Virtuoso NetSoft branding overlay.
# Restores Variphi UI sources after the build so viot.variphi.com is unaffected.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BRAND_DIR="${SCRIPT_DIR}/branding/virtuoso-netsoft"
UI="${TB_ROOT}/ui-ngx"
BACKUP_DIR="$(mktemp -d)"
IMAGE_TAG="${VIRTUOSO_TB_IMAGE:-virtuosonetsoft/tb-node:latest}"

cleanup() {
  if [[ -d "${BACKUP_DIR}" ]]; then
    echo "==> Restoring Variphi UI sources"
    cp -a "${BACKUP_DIR}/index.html" "${UI}/src/index.html"
    cp -a "${BACKUP_DIR}/environment.ts" "${UI}/src/environments/environment.ts"
    cp -a "${BACKUP_DIR}/environment.prod.ts" "${UI}/src/environments/environment.prod.ts"
    cp -a "${BACKUP_DIR}/footer.component.html" "${UI}/src/app/shared/components/footer.component.html"
    cp -a "${BACKUP_DIR}/login.component.html" "${UI}/src/app/modules/login/pages/login/login.component.html"
    cp -a "${BACKUP_DIR}/dashboard-page.component.html" "${UI}/src/app/modules/home/components/dashboard-page/dashboard-page.component.html"
    cp -a "${BACKUP_DIR}/app.component.ts" "${UI}/src/app/app.component.ts"
    cp -a "${BACKUP_DIR}/two-factor-auth-settings.component.ts" "${UI}/src/app/modules/home/pages/admin/two-factor-auth-settings.component.ts"
    cp -a "${BACKUP_DIR}/logo_title_white.svg" "${UI}/src/assets/logo_title_white.svg"
    cp -a "${BACKUP_DIR}/logo_white.svg" "${UI}/src/assets/logo_white.svg"
    cp -a "${BACKUP_DIR}/logo.component.scss" "${UI}/src/app/shared/components/logo.component.scss"
    cp -a "${BACKUP_DIR}/thingsboard.ico" "${UI}/src/thingsboard.ico"
    rm -f "${UI}/src/assets/virtuoso-logo.png" "${UI}/src/assets/virtuoso-favicon.png"
    rm -rf "${BACKUP_DIR}"
  fi
}
trap cleanup EXIT

echo "==> Backing up Variphi UI files"
cp -a "${UI}/src/index.html" "${BACKUP_DIR}/"
cp -a "${UI}/src/environments/environment.ts" "${BACKUP_DIR}/"
cp -a "${UI}/src/environments/environment.prod.ts" "${BACKUP_DIR}/"
cp -a "${UI}/src/app/shared/components/footer.component.html" "${BACKUP_DIR}/"
cp -a "${UI}/src/app/modules/login/pages/login/login.component.html" "${BACKUP_DIR}/"
cp -a "${UI}/src/app/modules/home/components/dashboard-page/dashboard-page.component.html" "${BACKUP_DIR}/"
cp -a "${UI}/src/app/app.component.ts" "${BACKUP_DIR}/"
cp -a "${UI}/src/app/modules/home/pages/admin/two-factor-auth-settings.component.ts" "${BACKUP_DIR}/"
cp -a "${UI}/src/assets/logo_title_white.svg" "${BACKUP_DIR}/"
cp -a "${UI}/src/assets/logo_white.svg" "${BACKUP_DIR}/"
cp -a "${UI}/src/app/shared/components/logo.component.scss" "${BACKUP_DIR}/"
cp -a "${UI}/src/thingsboard.ico" "${BACKUP_DIR}/"

echo "==> Preparing transparent Virtuoso branding assets"
bash "${BRAND_DIR}/make-transparent-assets.sh"

echo "==> Applying Virtuoso NetSoft branding overlay"
cp -a "${BRAND_DIR}/index.html" "${UI}/src/index.html"
cp -a "${BRAND_DIR}/environments/environment.ts" "${UI}/src/environments/environment.ts"
cp -a "${BRAND_DIR}/environments/environment.prod.ts" "${UI}/src/environments/environment.prod.ts"
cp -a "${BRAND_DIR}/footer.component.html" "${UI}/src/app/shared/components/footer.component.html"
cp -a "${BRAND_DIR}/login.component.html" "${UI}/src/app/modules/login/pages/login/login.component.html"
cp -a "${BRAND_DIR}/assets/logo_title_white.svg" "${UI}/src/assets/logo_title_white.svg"
cp -a "${BRAND_DIR}/assets/logo_white.svg" "${UI}/src/assets/logo_white.svg"
cp -a "${BRAND_DIR}/assets/virtuoso-logo.png" "${UI}/src/assets/virtuoso-logo.png"
cp -a "${BRAND_DIR}/assets/virtuoso-favicon.png" "${UI}/src/assets/virtuoso-favicon.png"
cp -a "${BRAND_DIR}/logo.component.scss" "${UI}/src/app/shared/components/logo.component.scss"
cp -a "${BRAND_DIR}/assets/virtuoso-favicon.ico" "${UI}/src/thingsboard.ico"

sed -i 's|Variphi IoT Version:|Virtuoso NetSoft Version:|' "${UI}/src/app/app.component.ts"
sed -i "s|value: 'Variphi IoT'|value: 'Virtuoso NetSoft'|" "${UI}/src/app/modules/home/pages/admin/two-factor-auth-settings.component.ts"
sed -i 's|https://variphi.com|https://virtuosonetsoft.com|g' "${UI}/src/app/modules/home/components/dashboard-page/dashboard-page.component.html"
sed -i 's|Variphi IoT|Virtuoso NetSoft|g' "${UI}/src/app/modules/home/components/dashboard-page/dashboard-page.component.html"

echo "==> Building tb-node image (this may take several minutes)"
cd "${TB_ROOT}"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-25-openjdk-amd64}"
export MAVEN_OPTS="${MAVEN_OPTS:--Xmx2560m}"
export NODE_OPTIONS="${NODE_OPTIONS:---max_old_space_size=4096}"

mvn -T2 clean install -DskipTests \
  -Dlicense.skip=true -Dcheckstyle.skip=true \
  -Dpkg.skip=false -Ddockerfile.skip=false \
  -pl msa/tb-node -am

docker tag thingsboard/tb-node:latest "${IMAGE_TAG}"
echo "==> Tagged ${IMAGE_TAG}"
