// ==UserScript==
// @name         YouTube Region changer Indicator
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  
// @match        https://www.youtube.com/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    function setRegionUS() {
        const regionEl = document.getElementById('country-code');
        if(regionEl && regionEl.textContent.trim() === 'RU') {
            regionEl.textContent = 'US';
        }
    }


    setRegionUS();


    const observer = new MutationObserver(() => setRegionUS());
    observer.observe(document.body, { childList: true, subtree: true });
})();
