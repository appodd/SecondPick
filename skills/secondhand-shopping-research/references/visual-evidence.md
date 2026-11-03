# Visual Evidence

## When To Read

Read only when the current question names a concrete visual uncertainty for a specific listing, such as a serial label, configuration screenshot, inspection report, visible defect, shutter count screen, or evidence conflict.

## Stage Goal

Reuse or collect the smallest listing-scoped image set that can address the visual question. OCR supports reading text in images; it is not a mandatory research step.

## Minimum Data Prerequisites

The selected listing must already have saved product image URLs from a valid detail snapshot. Use a listing ID and a bounded limit. Broad run-scoped processing is reserved for an explicit batch request.

## Reuse Saved Evidence

Reuse already downloaded media and existing OCR results before downloading or analyzing again. Do not rerun analysis just because an OCR backend is available.

## Canonical Commands

```powershell
python -m shopping_agent.cli download-media --listing-id 2064 --limit 8
python -m shopping_agent.cli analyze-images --listing-id 2064 --limit 8 --backend paddleocr
```

Use `--listing-id` for normal interactive work. Do not replace it with broad run scope unless the user explicitly requests batch visual analysis and accepts the cost.

## Output And Evidence Semantics

Media records preserve listing association and download status. OCR is fallible: stylized text, blur, compression, glare, cropping, and unsupported layouts can produce wrong or missing text. OCR and visual interpretation are signals, not proof of authenticity, repair history, liquid damage, MDM status, or hardware health.

State which image or OCR result supports a claim and retain uncertainty when the relevant region is absent or unreadable.

## Exit Conditions

Exit when the named visual question is answered as far as the saved media allows, or when no suitable image exists. Missing visual evidence should be reported as a gap rather than inferred.

## Related Stages

Detail investigation supplies image URLs and listing context. External verification may check what a photographed model or specification should mean, but it does not validate the photographed unit.
