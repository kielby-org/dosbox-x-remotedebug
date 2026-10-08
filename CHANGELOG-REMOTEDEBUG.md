# Changelog

## [0.1.1](https://github.com/kielby-org/dosbox-x-remotedebug/compare/remotedebug-v0.1.0...remotedebug-v0.1.1) (2026-10-08)


### Bug Fixes

* **remotedebug:** run the DOS or BIOS call a single step lands on ([#2](https://github.com/kielby-org/dosbox-x-remotedebug/issues/2)) ([7628465](https://github.com/kielby-org/dosbox-x-remotedebug/commit/7628465a9f9f436c420869098e2c31f16bd76741))

## 0.1.0 (2026-10-08)


### Features

* **remotedebug:** support Windows via Winsock ([a33af12](https://github.com/kielby-org/dosbox-x-remotedebug/commit/a33af1261bbf927071e0553b60b6ff510c543475))


### Bug Fixes

* **fpu:** include &lt;cmath&gt; for the std:: math functions ([26ddd6d](https://github.com/kielby-org/dosbox-x-remotedebug/commit/26ddd6d49f50c4d40e11cc190963ff3abe13cad6))
* **remotedebug:** listen on loopback by default ([a534d94](https://github.com/kielby-org/dosbox-x-remotedebug/commit/a534d947cce1656943072566603d3d72aece5fb2)), closes [#28](https://github.com/kielby-org/dosbox-x-remotedebug/issues/28)
* **remotedebug:** set SO_REUSEADDR and SO_REUSEPORT separately ([a33c70a](https://github.com/kielby-org/dosbox-x-remotedebug/commit/a33c70a8eaf0b3f8f2d43d15feb3877a2aef46e0))


### Build System

* **vs:** target Windows 7 and drop the XP build ([2b91a26](https://github.com/kielby-org/dosbox-x-remotedebug/commit/2b91a261cf8faa71eb519e182f0383531d949513))
