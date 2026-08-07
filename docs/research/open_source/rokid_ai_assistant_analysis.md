# RokidAIAssistant source analysis

- Repository: `zero2005x/RokidAIAssistant`; reviewed commit `777b5a33ccaa149161f1899649024adc661fd268`.
- License: no root `LICENSE`, `COPYING`, or SPDX declaration was present at the reviewed commit. Status: **REFERENCE_ONLY**.
- Stack and requirements: Android/Kotlin, Gradle multi-module project, Compose, Camera2, Bluetooth SPP, and proprietary Rokid CXR artifacts. A phone and compatible Rokid glasses are required for real transport; the repository also carries conventional Android fallbacks/tests.

## Real structure and entry points

`phone-app`, `glasses-app`, and `common` are separate Gradle modules. The primary lifecycle/UI entry points are each module's `AndroidManifest.xml` and `MainActivity.kt`. State is coordinated by `phone-app/.../viewmodel/PhoneViewModel.kt` and `glasses-app/.../viewmodel/GlassesViewModel.kt`. Shared constants and message framing live under `common/.../protocol`; photo framing is split between `common/.../protocol/photo/PhotoTransferConstants.kt`, glasses `PhotoTransferProtocol.kt`, and phone `BluetoothPhotoReceiver.kt`/`PhotoRepository.kt`.

## Capture, transport, HUD, and voice

- Glasses photo path: `GlassesViewModel` initializes `UnifiedCameraManager`; `GlassesCameraManager.kt`/`CameraService.kt` perform Camera2 capture and orientation normalization; `PhotoTransferProtocol.kt` writes framed bytes over the active `BluetoothSocket`; the phone receiver persists/dispatches them.
- Phone-side CXR path: `phone-app/.../service/cxr/CxrMobileManager.kt` wraps the mobile CXR client. `phone-app/build.gradle.kts` declares `com.rokid.cxr:client-m:1.0.4`.
- Glasses-side CXR path: `glasses-app/.../sdk/CxrServiceManager.kt` and `CxrCameraInterface.kt` wrap the bridge. `glasses-app/build.gradle.kts` declares `com.rokid.cxr:cxr-service-bridge:1.0-20250519.061355-45`.
- Bluetooth fallback/lifecycle: `BluetoothSppClient.kt` and phone `BluetoothSppManager.kt` implement connect/disconnect, streams, state, and error handling around UUID `a1b2c3d4-e5f6-7890-abcd-ef1234567890`; their tests cover duplicate-connect and disconnected paths. Reconnect is application-managed rather than a transport guarantee.
- Voice: `VoiceTriggerService.kt` is the glasses trigger path; phone STT services consume audio/requests. The CXR audio surface is wrapped rather than exposed to core logic.
- HUD/text return: phone responses become protocol messages and the glasses `MainActivity`/ViewModel renders state. The code does not establish a portable, open HUD API; CXR CustomView details remain SDK-bound.
- Agent/AI: phone-side provider classes and conversation ViewModels invoke configured backends. This is not suitable for GlanceFlow Agent reuse.

## Lifecycle and failure observations

Connection state is explicit, writes require a live socket, capture has permission/camera-busy paths, and photo reception has framing and timeout handling. The protocol has message types and photo boundaries, but it is not a documented durable exactly-once protocol; GlanceFlow should add its own message ID, acknowledgement, timeout, retry budget, and idempotency boundary.

## Reuse decision

Useful design references are the split phone/glasses modules, CXR-behind-interface pattern, Camera2 fallback, framed photo transfer, and explicit connection state. Code must not be copied because no clear license was found. AI providers, broad settings surface, direct backend selection, and its application state machine do not fit GlanceFlow. Agent Core, Safety Gate, temporal evidence, Calendar transaction, and recovery remain GlanceFlow-owned.
