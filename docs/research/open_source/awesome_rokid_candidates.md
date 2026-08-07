# awesome-rokid candidate verification

Index reviewed at `Anezium/awesome-rokid` commit `934394a95a345f679f1a487205d733a9c4063640`. The index has no license file and is used only to discover repositories. Descriptions were not treated as implementation evidence.

| Repo / reviewed commit | Device | Camera | Voice | HUD | CXR | Realtime | License | Reuse value |
|---|---|---|---|---|---|---|---|---|
| `Spphire/RokidGlassAI` `87f1979` | phone + glasses | Camera2/photo framing; CXR-shaped abstraction | phone/provider-oriented | glasses UI | artifacts declared, parts are wrappers/stubs | no | none found | REFERENCE_ONLY; closely overlaps RokidAIAssistant and includes placeholder SDK surfaces |
| `im-sanjay-sai/rokid__visual_agent` `d40c599` | phone + glasses | `PhotoResultCallback` path | CXR PCM stream (`openAudioRecord`) | `HudViewModel` | real `client-m` and bridge imports | streamed answer | none found | REFERENCE_ONLY; strongest CXR module separation reference |
| `RealComputer/GlassKit` `3711479` | glasses/backend examples | CameraX/Camera2 and WebRTC | mic/WebRTC/Vosk references | Android screen HUD examples | no core CXR dependency in reviewed examples | yes | MIT | REUSABLE_WITH_ATTRIBUTION; capture fallback and streaming patterns |
| `mlustosa/Rokid_Cam_monitor_for_Gemini_Live` `0eb6f41` | phone receiver | receives local RTMP via bundled MediaMTX | no | phone display only | no | RTMP | MIT file credits MediaMTX author; third-party scope requires care | design/reference for stream receiver, not glasses control |
| `Anezium/AssistBridge` `7b18062` | phone + glasses | no camera path | accessibility-captured text, not mic | `AssistantHudView` | bridge/client usage | message relay | none found | REFERENCE_ONLY; useful HUD relay/outbox/protocol design |

`RokidGlassAI` and `RokidAIAssistant` share substantial structure; neither provides a cleanly licensed SDK-independent module to import. `rokid__visual_agent` genuinely separates `transport-cxr-phone`, `transport-cxr-glasses`, and `protocol`, but without a license it remains reference-only. GlassKit is the best permissively licensed source for CameraX fallback and WebRTC capture mechanics. Camera Monitor proves an RTMP phone receiver, not a full glasses camera bridge. AssistBridge proves phone-to-glasses message/HUD relay, not image or voice capture.
