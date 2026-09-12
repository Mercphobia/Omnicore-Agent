#!/data/data/com.termux/files/usr/bin/bash
# OmniCore Android APK Builder
# Builds a Termux-based APK launcher for OmniCore
# Requires: termux, aapt, apksigner (Android SDK tools)

set -e

APP_NAME="OmniCore Agent"
PACKAGE="dev.mercphobia.omnicore"
VERSION="3.0.0"
VERSION_CODE="300"

OMNICORE_DIR="/storage/emulated/0/OmniCore"
BUILD_DIR="/tmp/omnicore-apk-build"
KEYSTORE="$HOME/.omnicore/release.keystore"

echo "══ OmniCore Android APK Builder ══"
echo ""

# Check tools
for tool in aapt apksigner; do
    if ! command -v $tool >/dev/null 2>&1; then
        echo "⚠ $tool not found. Install Android SDK tools."
        echo "  pkg install aapt apksigner"
    fi
done

# Clean build dir
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"/{assets,res/layout,res/values,META-INF}

# ── AndroidManifest.xml ──────────────────────────────────────────────

cat > "$BUILD_DIR/AndroidManifest.xml" << XML
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="$PACKAGE"
    android:versionCode="$VERSION_CODE"
    android:versionName="$VERSION">

    <uses-permission android:name="android.permission.INTERNET"/>
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE"/>

    <application
        android:label="$APP_NAME"
        android:icon="@drawable/ic_launcher"
        android:theme="@style/AppTheme">

        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:configChanges="orientation|screenSize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>

        <service
            android:name=".OmniCoreService"
            android:exported="false"
            android:foregroundServiceType="dataSync"/>

    </application>
</manifest>
XML

# ── Launcher script ──────────────────────────────────────────────────

cat > "$BUILD_DIR/assets/launch.sh" << 'SCRIPT'
#!/data/data/com.termux/files/usr/bin/bash
# OmniCore Launcher — started by Android activity

OMNICORE_DIR="/storage/emulated/0/OmniCore"
PID_FILE="$HOME/.omnicore/server.pid"

# Kill existing server
if [ -f "$PID_FILE" ]; then
    kill $(cat "$PID_FILE") 2>/dev/null
    rm "$PID_FILE"
fi

# Start server
cd "$OMNICORE_DIR"
python3 omnicore.py --server &
echo $! > "$PID_FILE"

# Start CLI
python3 ui/cli.py
SCRIPT
chmod +x "$BUILD_DIR/assets/launch.sh"

# ── Resources ─────────────────────────────────────────────────────────

cat > "$BUILD_DIR/res/values/strings.xml" << XML
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">OmniCore Agent</string>
    <string name="status_running">OmniCore server running on port 8000</string>
    <string name="status_stopped">Server stopped</string>
</resources>
XML

cat > "$BUILD_DIR/res/values/styles.xml" << XML
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="AppTheme" parent="android:Theme.Material.NoActionBar">
        <item name="android:colorPrimary">#0a0a0a</item>
        <item name="android:colorAccent">#00ff88</item>
        <item name="android:windowBackground">#0a0a0a</item>
        <item name="android:navigationBarColor">#0a0a0a</item>
    </style>
</resources>
XML

# ── Build APK ─────────────────────────────────────────────────────────

echo "Building APK..."

# Copy OmniCore (Python files only, skip heavy binaries)
mkdir -p "$BUILD_DIR/assets/omnicore"
rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='rust/target' --exclude='go/agent/omnicore-agent' \
    "$OMNICORE_DIR/" "$BUILD_DIR/assets/omnicore/" 2>/dev/null || \
    cp -a "$OMNICORE_DIR"/* "$BUILD_DIR/assets/omnicore/" 2>/dev/null

# Generate R.java
aapt package -f -m \
    -J "$BUILD_DIR/gen" \
    -M "$BUILD_DIR/AndroidManifest.xml" \
    -S "$BUILD_DIR/res" \
    -I "$ANDROID_HOME/platforms/android-34/android.jar" 2>/dev/null || true

# Package resources
aapt package -f \
    -M "$BUILD_DIR/AndroidManifest.xml" \
    -S "$BUILD_DIR/res" \
    -A "$BUILD_DIR/assets" \
    -F "$BUILD_DIR/omnicore-unsigned.apk" 2>/dev/null || {
    echo "⚠ aapt package failed — trying alternative..."
    # Fallback: create minimal APK zip
    cd "$BUILD_DIR"
    zip -qr omnicore-unsigned.apk AndroidManifest.xml assets/ res/ 2>/dev/null
}

# Sign APK (if keystore exists)
if [ -f "$KEYSTORE" ]; then
    apksigner sign --ks "$KEYSTORE" \
        --out "$HOME/OmniCore-v$VERSION.apk" \
        "$BUILD_DIR/omnicore-unsigned.apk" 2>/dev/null && \
        echo "✓ Signed: $HOME/OmniCore-v$VERSION.apk" || \
        echo "⚠ Signing failed — unsigned APK at $BUILD_DIR/omnicore-unsigned.apk"
else
    # Generate debug keystore
    keytool -genkey -v \
        -keystore "$BUILD_DIR/debug.keystore" \
        -alias omnicore \
        -keyalg RSA -keysize 2048 -validity 10000 \
        -storepass android -keypass android \
        -dname "CN=OmniCore" 2>/dev/null

    apksigner sign --ks "$BUILD_DIR/debug.keystore" \
        --ks-pass pass:android \
        --out "$HOME/OmniCore-v$VERSION-debug.apk" \
        "$BUILD_DIR/omnicore-unsigned.apk" 2>/dev/null && \
        echo "✓ Debug APK: $HOME/OmniCore-v$VERSION-debug.apk" || \
        echo "⚠ APK at $BUILD_DIR/omnicore-unsigned.apk"
fi

echo ""
echo "══ Done ══"
echo "APK: $HOME/OmniCore-v$VERSION*.apk"
echo ""
echo "To install:"
echo "  adb install OmniCore-v$VERSION-debug.apk"
echo ""
echo "Requirements on device:"
echo "  - Termux installed"
echo "  - Python 3.11+ in Termux"
echo "  - pip install httpx pyyaml rich"