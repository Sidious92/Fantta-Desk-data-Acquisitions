#!/usr/bin/env bash
set -euo pipefail
APP_ID="com.deepfieldresearch.fantadesk"
APK="app/android/app/build/outputs/apk/debug/app-debug.apk"
test -s "$APK"
adb wait-for-device
adb install -r "$APK" >/dev/null
adb shell am force-stop "$APP_ID" || true
adb shell am start -n "$APP_ID/.MainActivity"
sleep 5

echo "FANTADESK_EMULATOR_CHECK: first launch"
if ! adb shell pidof "$APP_ID" >/dev/null; then echo "APP_PROCESS_MISSING"; exit 1; fi
FOUND=0
for n in $(seq 1 12); do
  adb shell uiautomator dump /sdcard/fantadesk-window.xml >/dev/null 2>&1 || true
  XML="$(adb exec-out cat /sdcard/fantadesk-window.xml 2>/dev/null || true)"
  if printf '%s' "$XML" | grep -Eq 'text="Accedi"|text="FantaDesk"|content-desc="Accedi"'; then
    FOUND=1
    if printf '%s' "$XML" | grep -q "Continua con Google"; then
      echo "NATIVE_GOOGLE_AUTH_BUTTON_UNEXPECTED"
      exit 1
    fi
    break
  fi
  sleep 5
done
if [ "$FOUND" -ne 1 ]; then
  echo "LOGIN_SCREEN_NOT_OBSERVED_IN_UI_HIERARCHY"
  XML="$(adb exec-out cat /sdcard/fantadesk-window.xml 2>/dev/null || true)"
  printf 'UI_XML_BYTES=%s NODE_COUNT=%s WEBVIEW_TAG=%s\\n' "${#XML}" "$(printf '%s' "$XML" | grep -o '<node' | wc -l)" "$(printf '%s' "$XML" | grep -c 'android.webkit.WebView' || true)"
  adb exec-out screencap -p > /tmp/fantadesk-guest.png
  file /tmp/fantadesk-guest.png
  if command -v identify >/dev/null 2>&1; then
    identify -format 'SCREEN_PIXEL_STDDEV=%[standard-deviation]\\n' /tmp/fantadesk-guest.png
  fi
  PID="$(adb shell pidof "$APP_ID" | tr -d '\\r')"
  if [ -n "$PID" ]; then
    adb forward tcp:9222 "localabstract:webview_devtools_remote_${PID}" >/dev/null || true
    if node .github/scripts/fantadesk-b12-android-cdp.mjs; then
      FOUND=1
      echo "ANDROID_ACCESSIBILITY_HIERARCHY_INCOMPLETE: WebView guest DOM validated via debug-only CDP"
    fi
    adb forward --remove tcp:9222 >/dev/null 2>&1 || true
  fi
  if [ "$FOUND" -ne 1 ]; then
    echo "NO_GUEST_UI_CONFIRMED; do not treat app as operational."
    exit 1
  fi
fi
echo "FANTADESK_EMULATOR_CHECK: guest login visible and Google native flow disabled"

adb shell input keyevent KEYCODE_HOME
sleep 2
adb shell monkey -p "$APP_ID" -c android.intent.category.LAUNCHER 1 >/dev/null
sleep 4
adb shell pidof "$APP_ID" >/dev/null
echo "FANTADESK_EMULATOR_CHECK: resume from background PASS"

adb shell settings put system accelerometer_rotation 0
adb shell settings put system user_rotation 1
sleep 3
adb shell settings put system user_rotation 0
sleep 3
adb shell pidof "$APP_ID" >/dev/null
echo "FANTADESK_EMULATOR_CHECK: rotation/recovery PASS"

CRASH="$(adb logcat -d -b crash 2>/dev/null || true)"
if printf '%s' "$CRASH" | grep -Fq "$APP_ID"; then
  echo "FANTADESK_EMULATOR_CHECK: APP_CRASH_OBSERVED"
  exit 1
fi
echo "FANTADESK_EMULATOR_SMOKE_PASS: no login issued, no account created, no private binary uploaded"
