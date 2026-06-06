# Maintainer: Chase M <chasem> — submitter for moment
# Contributor: Chase M <chasem>
#
# GPU-accelerated game clip manager for Linux — capture, edit, and share your
# gaming moments.
#
# Build:  makepkg -si
# Source: https://github.com/SpinGiantCRM/moment

pkgname=moment
pkgver=0.3.17
pkgrel=1
epoch=
pkgdesc="GPU-accelerated game clip manager for Linux. Capture, edit, and share your gaming moments."
arch=('any')
url="https://github.com/SpinGiantCRM/moment"
license=('GPL-3.0-only')
depends=(
    'python'
    'python-pyqt6'
    'python-cryptography'
    'python-keyring'
    'python-setuptools'
    'sqlcipher'
    'ffmpeg'
    'rclone'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-setuptools'
)
optdepends=(
    'gpu-screen-recorder: hardware-accelerated clip capture'
    'python-discord.py: Discord bot integration'
    'python-fastmcp: AI agent MCP server'
    'python-python-magic: MIME type validation for imports'
)
source=("${pkgname}-${pkgver}.tar.gz::${url}/archive/refs/tags/v${pkgver}.tar.gz")
sha256sums=('af6877aba2297d6a5640db3607e9fc8978c7c1d049626583b575fa6322e81c10')

package() {
    cd "${srcdir}/${pkgname}-${pkgver}"

    python -m build --wheel --no-isolation
    python -m installer --destdir="${pkgdir}" dist/*.whl

    # Desktop file
    install -Dm644 install/moment.desktop \
        "${pkgdir}/usr/share/applications/moment.desktop"

    # Scalable SVG icon
    install -Dm644 src/moment/ui/assets/icons/moment.svg \
        "${pkgdir}/usr/share/icons/hicolor/scalable/apps/moment.svg"

    # Rendered PNG icons (48, 64, 128, 256)
    for size in 48 64 128 256; do
        if command -v rsvg-convert &>/dev/null; then
            install -d "${pkgdir}/usr/share/icons/hicolor/${size}x${size}/apps"
            rsvg-convert -w "${size}" -h "${size}" \
                src/moment/ui/assets/icons/moment.svg \
                -o "${pkgdir}/usr/share/icons/hicolor/${size}x${size}/apps/moment.png"
        fi
    done

    # systemd user service (Discord bot)
    install -Dm644 install/moment-bot.service \
        "${pkgdir}/usr/lib/systemd/user/moment-bot.service"

    # License
    install -Dm644 LICENSE "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
}
