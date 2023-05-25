# KubeScaler

> Make your Kubernetes cluster YUGE! Or Smol. :)

<!-- ALL-CONTRIBUTORS-BADGE:START - Do not remove or modify this section -->
[![All Contributors](https://img.shields.io/badge/all_contributors-1-orange.svg?style=flat-square)](#contributors-)
<!-- ALL-CONTRIBUTORS-BADGE:END -->
[![PyPI](https://img.shields.io/pypi/v/kubescaler)](https://pypi.org/project/kubescaler/)

<a target="_blank" rel="noopener noreferrer" href="https://github.com/converged-computing/kubescaler/blob/main/docs/assets/img/logo-transparent.png">
    <img align="right" style="width: 250px; float: right; padding-left: 20px;" src="https://github.com/converged-computing/kubescaler/raw/main/docs/assets/img/logo-transparent.png" alt="KubeScaler Logo">
</a>

This is a set of helper Python classes that make it easy to add elasticity, or scaling
up and down, of your Kubernetes clusters in Python. We currently have support for the clouds
we use, namely:

- Google (GKE)
- Amazon (EKS)

🚧️ **under development** 🚧️

This tool is under development and is not ready for production use. Documentation
and examples coming soon!

## 😁️ Contributors 😁️

We use the [all-contributors](https://github.com/all-contributors/all-contributors)
tool to generate a contributors graphic below.

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://vsoch.github.io"><img src="https://avatars.githubusercontent.com/u/814322?v=4?s=100" width="100px;" alt="Vanessasaurus"/><br /><sub><b>Vanessasaurus</b></sub></a><br /><a href="https://github.com/converged-computing/kubescaler/commits?author=vsoch" title="Code">💻</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->

## TODO

 - fix up GKE scale function to only be one function, we don't need to reset max and min again
 - run experiments for scaling on EKS

## License

HPCIC DevTools is distributed under the terms of the MIT license.
All new contributions must be made under this license.

See [LICENSE](https://github.com/converged-computing/kubescaler/blob/main/LICENSE),
[COPYRIGHT](https://github.com/converged-computing/kubescaler/blob/main/COPYRIGHT), and
[NOTICE](https://github.com/converged-computing/kubescaler/blob/main/NOTICE) for details.

SPDX-License-Identifier: (MIT)

LLNL-CODE- 842614
