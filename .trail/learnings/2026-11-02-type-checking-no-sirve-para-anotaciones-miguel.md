---
title: TYPE_CHECKING no sirve para anotaciones evaluadas al definirse en Python 3.12 y 3.13
author: Miguel
date: 2026-11-02
standing: true
id: l-3f4217e5
scope: repo
status: active
src: init-review
---

## Watch out
- untangle aconsejaba TYPE_CHECKING para anotaciones que esas versiones evalúan al definir, lo que daba NameError.
- In the code: Para anotaciones exige `from __future__ import annotations` o anotaciones entre comillas (`UseContext.QUOTED`); el paso `POSTPONE_ANNOTATIONS` añade el future import.

_From PR #57 here, Oct 10._
