# Model license

The [MIT License](LICENSE) covers the source code of this repository only.
It does **not** cover the offline translation model.

## NLLB-200 translation model: CC-BY-NC-4.0

The local offline backend uses
[NLLB-200-distilled-600M](https://huggingface.co/facebook/nllb-200-distilled-600M)
by Meta AI (NLLB Team), licensed under
[Creative Commons Attribution-NonCommercial 4.0 International (CC-BY-NC-4.0)](https://creativecommons.org/licenses/by-nc/4.0/).

The same license applies to every model built from it:

- the int8 CTranslate2 build published as
  [Alhite/overlay-translator-nllb-int8](https://huggingface.co/Alhite/overlay-translator-nllb-int8)
  (downloaded by `scripts/download_model.py` / `download_model.bat`);
- any fine-tuned version produced by `training/`;
- a model you convert yourself with `ct2-transformers-converter`.

What this means:

- **Non-commercial use only.** You may not use the model, or the app with the
  model, for commercial purposes.
- **Attribution.** When you share the model or a derivative, credit the NLLB Team,
  link to the license, and say what you changed.

The model weights are not stored in this repository (`models/` is git-ignored).
The app itself works without them, through the cloud translation backends.

Citation:

> NLLB Team et al. *No Language Left Behind: Scaling Human-Centered Machine
> Translation.* arXiv:2207.04672, 2022.

## Training data

The fine-tuning pipeline in `training/` uses the
[FLORES-200](https://huggingface.co/datasets/facebook/flores) dataset by the NLLB Team,
licensed under [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/).
The dataset is not stored in this repository.
