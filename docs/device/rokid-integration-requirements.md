# Rokid integration requirements

Current status: **NOT_YET_TESTED_ON_ROKID**.

A real implementation requires a supported Rokid model, paired supported
Android phone if the chosen SDK requires it, official developer access and
Maven artifacts, documented application authentication, camera/microphone/
Bluetooth permissions, transport protocol documentation, and test credentials
kept locally and untracked.

Before enabling it, verify SDK initialization and authentication from official
documentation, capture byte ownership/lifetime, audio format, HUD limits,
connection callbacks, timeout behavior, message acknowledgement, background
restrictions, and license/distribution rights. Until then,
`RokidSDKUnavailableAdapter.healthcheck()` is false and operations return
`SDK_UNAVAILABLE`.
