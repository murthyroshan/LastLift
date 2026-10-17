# Film opening: "Ask it with your eyes closed" (MS6)

Audio first, black screen. The first 15 seconds of the 2:30 video, built from eyes-free mode (`?eyesfree=1`) and a
recorded run, so it plays the same every time and needs no backend.

| Time | Picture | Sound |
|---|---|---|
| 0:00-0:03 | Black. A small caption fades in: "Close your eyes. Ask out loud." | Start earcon (two rising notes) |
| 0:03-0:07 | Still black; the caption shows the question | The author asks: "Can I get step-free onto the Wonderland-bound platform at Revere Beach?" |
| 0:07-0:12 | Fade up on eyes-free mode, transcript growing | LastLift answers (browser speech): "Not directly. Lift 885 is out. Take lift 884, ride to Beachmont and back, about 17 minutes." |
| 0:12-0:15 | Cut to the station x-ray: the route draws, 885 hatched, 884 gold | "Every fact checked against a FalkorDB graph." Title: LastLift |

Muted-safe version: `opener.srt` holds the captions; `web/scripts/record_opener.mjs` records the page with the
captions burned in (WebM; `ffmpeg -i opener.webm opener.mp4` to convert). The voice-over and the final edit are the
author's; the facts on screen come from the recorded run `revere-board` (hash-chained, "Verify this replay").
