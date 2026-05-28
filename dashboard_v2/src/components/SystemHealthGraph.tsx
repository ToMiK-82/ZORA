import React, { useMemo, useState, useRef, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSystemGraph } from '../api/dashboardApi';
import { FiServer } from 'react-icons/fi';
import type { SystemGraphNode } from '../types';
import { Card, CardContent } from './ui/card';

// ── Inline SVG Logos (white-filled for dark background) ──

const ZoraLogo = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 64 64" fill="white">
    <path d="M13.402 15.904h5.15v-15h-5.15c-4.142 0-7.5 3.358-7.5 7.5s3.358 7.5 7.5 7.5z"/>
    <path d="M58.098 55.6c0 4.14-3.36 7.5-7.5 7.5h-5.15v-15h5.15c4.14 0 7.5 3.35 7.5 7.5z"/>
    <path d="M26.508 48.1h13.03v15h-22.18c-4.55 0-8.61-2.72-10.36-6.92-1.74-4.21-.78-9 2.43-12.22l28.06-28.06h-13.03v-15h22.18c4.55 0 8.61 2.72 10.36 6.92 1.74 4.21.78 9-2.43 12.22z"/>
  </svg>
);

const QdrantLogo = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 346 400" fill="white">
    <polygon points="173.21,0 0,100 0,300 173.21,400 238.16,362.5 238.16,287.5 173.21,325 64.96,262.5 64.96,137.5 173.21,75 281.46,137.5 281.46,387.5 346.42,350 346.42,100"/>
    <polygon points="108.26,162.5 108.26,237.5 173.21,275 238.16,237.5 238.16,162.5 173.21,125"/>
  </svg>
);

const OllamaLogo = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 646 854" fill="white">
    <path d="M140.629 0.2399C132.66 1.5273 123.097 5.6957 116.354 10.845C95.941 26.3541 80.1253 59.2728 73.4435 100.283C70.9302 115.792 69.2138 137.309 69.2138 153.738C69.2138 173.109 71.4819 197.874 74.7309 214.977C75.4665 218.778 75.8343 222.15 75.5278 222.395C75.2826 222.64 72.2788 225.092 68.9072 227.789C57.3827 236.984 44.2029 251.145 35.1304 264.08C17.7209 288.784 6.44151 316.86 1.72133 347.265C-0.117698 359.28 -0.608106 383.555 0.863118 395.57C4.11207 423.278 12.449 446.695 26.7321 468.151L31.391 475.078L30.0424 477.346C20.4794 493.407 12.3264 516.64 8.52575 538.953C5.522 556.608 5.15419 561.328 5.15419 584.99C5.15419 608.837 5.4607 613.557 8.28054 630.047C11.6521 649.786 18.5178 670.689 26.1804 684.605C28.6938 689.141 34.8239 698.581 35.5595 699.072C35.8047 699.194 35.0691 701.462 33.9044 704.098C25.077 723.408 17.537 749.093 14.4106 770.733C12.2038 785.567 11.8973 790.349 11.8973 805.981C11.8973 825.903 13.0007 835.589 17.1692 851.466L17.7822 853.795H44.019H70.3172L68.6007 850.546C57.9957 830.93 57.0149 794.517 66.1487 758.166C70.3172 741.369 75.0374 729.048 83.8647 712.067L89.1366 701.769V695.455C89.1366 689.57 89.014 688.896 87.1137 685.034C85.6424 682.091 83.6808 679.578 80.1866 676.145C74.2404 670.383 69.9494 664.314 66.5165 656.835C51.4365 624.1 48.494 575.489 59.0991 534.049C63.5128 516.762 70.8076 501.376 78.4702 492.978C83.6808 487.215 86.378 480.779 86.378 474.097C86.378 467.17 83.926 461.469 78.4089 455.523C62.5932 438.604 52.8464 418.006 49.3522 394.038C44.3868 359.893 53.3981 322.683 73.8726 293.198C93.9181 264.263 122.055 245.689 153.503 240.724C160.552 239.559 173.732 239.743 181.088 241.092C189.119 242.502 194.145 242.072 199.295 239.62C205.67 236.617 208.858 232.877 212.597 224.295C215.907 216.633 218.482 212.464 225.409 203.821C233.746 193.461 241.776 186.411 254.649 177.89C269.362 168.266 286.097 161.278 302.771 157.906C308.839 156.68 311.659 156.496 323 156.496C334.341 156.496 337.161 156.68 343.229 157.906C367.688 162.872 391.964 175.5 411.335 193.399C415.503 197.261 425.495 209.644 428.683 214.794C429.909 216.816 432.055 221.108 433.403 224.295C437.142 232.877 440.33 236.617 446.705 239.62C451.671 242.011 456.881 242.502 464.605 241.214C476.804 239.13 486.183 239.314 498.137 241.766C538.841 249.98 574.273 283.512 589.966 328.446C603.636 367.862 599.774 409.118 579.422 440.626C575.989 445.96 572.556 450.251 567.591 455.523C556.863 466.986 556.863 481.208 567.53 492.978C585.062 512.165 596.035 559.367 592.724 600.99C590.518 628.453 583.468 653.035 573.782 666.95C572.066 669.402 568.511 673.57 565.813 676.145C562.319 679.578 560.358 682.091 558.886 685.034C556.986 688.896 556.863 689.57 556.863 695.455V701.769L562.135 712.067C570.963 729.048 575.683 741.369 579.851 758.166C588.863 794.027 588.066 829.704 577.767 849.995C576.909 851.711 576.173 853.305 576.173 853.489C576.173 853.673 587.882 853.795 602.226 853.795H628.218L628.892 851.159C629.26 849.75 629.873 847.604 630.179 846.378C630.854 843.681 632.202 835.712 633.306 828.049C634.348 820.325 634.348 791.881 633.306 783.299C629.383 752.158 622.823 727.454 612.096 704.098C610.931 701.462 610.195 699.194 610.44 699.072C610.747 698.888 612.463 696.436 614.302 693.677C627.666 673.448 635.88 648.008 640.049 614.415C641.152 605.158 641.152 565.374 640.049 556.485C637.106 533.559 633.551 517.988 627.666 502.234C625.214 495.675 618.716 481.821 615.958 477.346L614.609 475.078L619.268 468.151C633.551 446.695 641.888 423.278 645.137 395.57C646.608 383.555 646.118 359.28 644.279 347.265C639.497 316.798 628.279 288.845 610.87 264.08C601.797 251.145 588.617 236.984 577.093 227.789C573.721 225.092 570.717 222.64 570.472 222.395C570.166 222.15 570.534 218.778 571.269 214.977C578.687 176.296 578.441 128.053 570.656 90.3524C563.913 57.4951 551.653 31.3808 535.837 16.3008C523.209 4.28578 510.336 -0.863507 494.888 0.11731C459.456 2.20154 430.89 42.9667 419.61 107.21C417.771 117.57 416.178 129.708 416.178 133.018C416.178 134.305 415.932 135.347 415.626 135.347C415.319 135.347 412.929 134.121 410.354 132.589C383.014 116.405 352.608 107.762 323 107.762C293.392 107.762 262.986 116.405 235.646 132.589C233.071 134.121 230.681 135.347 230.374 135.347C230.068 135.347 229.822 134.305 229.822 133.018C229.822 129.585 228.167 117.08 226.39 107.21C216.152 49.5259 192.674 11.3354 161.472 1.71112C157.181 0.423799 144.982 -0.434382 140.629 0.2399Z" fill="white"/>
    <path d="M313.498 358.237C300.195 359.525 296.579 360.015 290.203 361.303C279.843 363.448 265.989 368.23 256.365 372.95C222.895 389.317 199.846 416.596 192.796 448.166C191.386 454.419 191.202 456.503 191.202 467.047C191.202 477.468 191.386 479.736 192.735 485.682C202.114 526.938 240.12 557.405 289.284 562.983C299.95 564.148 346.049 564.148 356.715 562.983C396.193 558.508 430.154 537.114 445.418 507.076C449.463 499.046 451.425 493.835 453.264 485.682C454.613 479.736 454.797 477.468 454.797 467.047C454.797 456.503 454.613 454.419 453.203 448.166C442.965 402.313 398.461 366.207 343.903 359.341C336.792 358.483 318.157 357.747 313.498 358.237Z" fill="white"/>
    <path d="M150.744 365.165C139.894 368.598 131.802 376.567 127.634 387.908C125.611 393.303 124.63 401.824 125.488 406.421C127.511 417.394 136.522 427.386 146.76 430.145C159.633 433.516 169.257 431.309 177.778 422.85C182.743 418.007 185.441 413.777 188.138 406.911C190.099 402.069 190.222 401.211 190.222 394.345L190.283 386.989L187.709 381.717C183.601 373.38 176.184 367.188 167.602 364.92C162.759 363.694 154.974 363.756 150.744 365.165Z" fill="white"/>
    <path d="M478.153 364.982C469.755 367.25 462.276 373.502 458.291 381.717L455.717 386.989L455.778 394.345C455.778 401.211 455.901 402.069 457.862 406.911C460.56 413.777 463.257 418.007 468.222 422.85C476.743 431.309 486.367 433.516 499.241 430.145C506.658 428.183 514.075 421.93 517.631 414.635C520.696 408.444 521.431 403.969 520.451 396.919C518.183 380.797 508.742 369.089 494.704 364.982C490.597 363.756 482.628 363.756 478.153 364.982Z" fill="white"/>
  </svg>
);

const DeepSeekLogo = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 1000 750" fill="white">
    <path d="M989.56 63.05c-10.54-5.36-15.21 4.67-21.43 9.85-2.07 1.56-3.8 3.8-5.7 5.7-15.38 16.94-33.53 28-57.21 26.62-34.4-1.9-63.95 9.16-90.05 35.95-5.53-33.18-24.02-52.89-52.02-65.68-14.7-6.57-29.38-13.13-39.75-27.48-7.09-10.37-9.16-21.78-12.62-33.01-2.42-6.74-4.67-13.65-12.27-14.86-8.3-1.21-11.58 5.88-14.86 11.75-12.96 24.37-18.15 51.16-17.63 78.12 1.21 61.01 26.44 109.58 76.57 144.14 5.7 3.8 7.26 7.78 5.36 13.65-3.28 11.93-7.43 23.33-11.06 35.26-2.25 7.6-5.7 9.33-13.65 6.05-27.48-11.75-51.33-29.04-72.42-50.12-35.6-35.09-67.92-73.97-108.2-104.39-9.33-7.09-18.84-13.65-28.69-19.88-40.96-40.62 5.53-73.97 16.25-77.95 11.23-4.15 3.8-18.32-32.5-18.32-36.3 0-69.48 12.62-111.99 29.21-6.05 2.42-12.62 4.32-19.36 5.7-38.37-7.43-78.3-8.99-120.12-4.32-78.47 8.99-141.2 46.84-187.35 111.3C3.37 237.96-9.59 326.27 6.31 418.22c16.76 96.96 65.33 177.15 139.99 239.89 77.43 65.16 166.61 96.96 268.24 90.91 61.87-3.63 130.66-12.1 208.09-78.99 19.7 9.85 40.1 13.83 74.15 16.94 26.27 2.42 51.5-1.38 71.2-5.53 30.59-6.57 28.52-35.43 17.29-40.79-89.7-42.52-70-25.23-87.97-39.23 45.63-55.13 114.42-112.17 141.38-297.28 2.07-14.69.35-24.02 0-35.95-.17-7.26 1.38-10.02 9.5-10.89 22.64-2.59 44.42-8.81 64.47-20.05 58.07-32.49 81.58-85.55 87.11-149.33 1.21-14.57.18-24.59-9.84-29.6zM482.47 636.68c-86.94-69.65-129.11-92.64-146.56-91.6-16.25 1.04-13.48 19.88-9.85 32.32 3.8 12.27 8.64 20.74 15.55 31.46 4.67 7.09 7.95 17.63-4.84 25.58-28 17.63-76.74-6.05-78.98-7.09-56.69-34.05-104.05-78.98-137.58-140.51-32.15-59.11-50.99-122.54-54.1-190.12-.7-16.42 3.98-22.12 19.88-25.23 21.09-3.8 42.69-4.67 63.78-1.56 88.83 13.13 164.36 53.58 227.79 117.7 36.3 36.47 63.6 80.19 91.78 122.71 30.07 45.28 62.22 88.32 103.35 123.75 14.52 12.44 26.1 21.78 37.16 28.69 37.11 23.67 -13.69 24.53 -51.89 -6.22z" fill="white"/>
  </svg>
);

const PostgresLogo = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 256 264" fill="white">
    <path d="M255.008 158.086c-1.535-4.648-5.556-7.887-10.756-8.664-2.452-.366-5.26-.21-8.583.475-5.792 1.195-10.089 1.65-13.224 1.738 11.836-19.985 21.461-42.776 27.002-64.229 8.959-34.688 4.172-50.491-1.423-57.64-14.807-18.919-36.409-29.083-62.472-29.395-13.902-.17-26.108 2.575-32.474 4.549-5.928-1.045-12.303-1.63-18.991-1.738-12.534-.2-23.611 2.533-33.076 8.15-5.241-1.772-13.65-4.27-23.362-5.864-22.842-3.75-41.252-.828-54.716 8.685C6.623 25.672-.937 45.684.462 73.634c.443 8.874 5.408 35.873 13.223 61.48 4.492 14.717 9.282 26.94 14.237 36.33 7.027 13.314 14.545 21.156 22.986 23.971 4.732 1.577 13.328 2.68 22.37-4.849 1.145 1.387 2.674 2.766 4.703 4.047 2.577 1.625 5.728 2.953 8.875 3.74 11.341 2.836 21.964 2.126 31.027-1.847.055 1.612.099 3.152.135 4.482.06 2.157.12 4.272.199 6.25.537 13.374 1.447 23.773 4.143 31.049.148.401.347 1.01.557 1.656 1.345 4.119 3.594 11.012 9.316 16.412 5.926 5.592 13.092 7.308 19.656 7.307 3.292 0 6.433-.432 9.188-1.022 9.82-2.104 20.973-5.311 29.04-16.798 7.628-10.86 11.337-27.217 12.008-52.991.087-.728.167-1.424.245-2.087.052-.458.105-.915.159-1.372l1.797.158.463.031c10.003.456 22.233-1.665 29.744-5.154 5.935-2.755 24.954-12.795 20.476-26.352z" fill="white"/>
  </svg>
);

const DockerLogo = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 800 800" fill="white">
    <path d="M627.3 301.5c-1.6-1.3-16.1-12.2-46.7-12.2-8.1 0-16.2.6-24.2 2.1-5.9-40.7-39.5-60.5-41-61.4l-8.2-4.8-5.4 7.8c-6.8 10.5-11.7 22-14.6 34.2-5.5 23.2-2.2 45 9.6 63.6-14.2 7.9-37.1 9.9-41.7 10h-230c-9.9 0-17.9 8-17.9 17.9-.4 33.1 5.2 66 16.5 97.1 13 34.2 32.4 59.3 57.6 74.7 28.2 17.3 74.1 27.2 126.2 27.2 23.5.1 47-2.1 70.1-6.4 32.1-5.9 63-17.1 91.4-33.2 23.4-13.6 44.5-30.8 62.4-51.1 29.9-33.9 47.8-71.7 61.1-105.2h5.3c32.8 0 53-13.1 64.1-24.1 7.4-7 13.2-15.5 16.9-25l2.3-6.9-5.7-4.3zM152 329.9h50.7c2.4 0 4.4-2 4.4-4.4v-45.1c0-2.4-2-4.4-4.4-4.5H152c-2.4 0-4.4 2-4.4 4.4v45.2c0 2.5 2 4.4 4.4 4.4m69.9 0h50.7c2.4 0 4.4-2 4.4-4.4v-45.1c0-2.4-2-4.4-4.4-4.5h-50.7c-2.5 0-4.5 2-4.5 4.5v45.1c0 2.5 2 4.4 4.5 4.4m70.8.1h50.7c2.4 0 4.4-2 4.4-4.4v-45.1c0-2.4-2-4.4-4.4-4.5h-50.7c-2.4 0-4.4 2-4.4 4.4v45.2c0 2.4 2 4.3 4.4 4.4m70.1 0h50.7c2.4 0 4.4-2 4.5-4.4v-45.1c0-2.5-2-4.5-4.5-4.5h-50.7c-2.4 0-4.4 2-4.4 4.4v45.2c0 2.4 1.9 4.4 4.4 4.4m-141-65h50.7c2.4 0 4.4-2 4.4-4.5v-45.1c0-2.4-2-4.4-4.4-4.4h-50.7c-2.5 0-4.4 2-4.5 4.4v45.1c.1 2.5 2.1 4.5 4.5 4.5m70.9 0h50.7c2.4 0 4.4-2 4.4-4.5v-45.1c0-2.4-2-4.4-4.4-4.4h-50.7c-2.4 0-4.4 2-4.4 4.4v45.1c0 2.5 2 4.5 4.4 4.5m70.1 0h50.7c2.5 0 4.4-2 4.5-4.5v-45.1c0-2.5-2-4.4-4.5-4.4h-50.7c-2.4 0-4.4 2-4.4 4.4v45.1c0 2.5 1.9 4.5 4.4 4.5m0-64.9h50.7c2.5 0 4.5-2 4.5-4.5v-45.2c0-2.4-2-4.4-4.5-4.4h-50.7c-2.4 0-4.4 2-4.4 4.4v45.2c0 2.5 1.9 4.5 4.4 4.5M433.4 330h50.7c2.4 0 4.4-2 4.4-4.4v-45.1c0-2.5-2-4.4-4.4-4.5H433.4c-2.4 0-4.4 2-4.4 4.4v45.2c0 2.4 2 4.4 4.4 4.4" fill="white"/>
  </svg>
);

const OneCLogo = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 1000 781" fill="white">
    <path d="M476.9 509.1c-14-.9-30.1-3.4-42.9-7.1-2.4-.7-12.3-4.3-14.8-5.5-44.3-20.5-75.2-65.4-75.2-117.4 0-71.3 58-129.4 129.4-129.4 70.7 0 128.4 57.1 129.3 127.6h46.7c-1-96.3-79.6-174.3-176.1-174.3-97.1 0-176.1 79-176.1 176.1 0 67 37.6 125.2 92.8 154.9 9.9 5.3 24.2 10.7 29.1 12.2 15.7 4.7 35 7.8 52.2 9.1 5.8.4 26.2.7 32.1.7h321.9v-46.6H504.1c-4.3 0-23 .1-27.2-.2zM504.1 436c-3.4 0-21.2-.1-24.5-.4-5.6-.5-13.6-1.3-18.8-2.5-5.8-1.6-11.3-3.6-13.8-5-17.4-9.4-29.2-27.8-29.2-48.9 0-30.8 24.9-55.7 55.7-55.7 30.1 0 54.6 24 55.6 53.9H574c-.9-54.7-45.6-98.8-100.5-98.8-55.6 0-100.7 45-100.7 100.6 0 39.2 22.5 73.1 55.2 89.6 5 2.9 14.5 6 17.2 6.7 9.2 2.4 21.6 4.1 31.7 4.8 3.7.3 22 .4 25.8.5v.1h322.7v-45H504.1zM268.5 555.9h-47V249.9h-68.8v-47.1h115.8v353.1zM101 273.4v45.2h51.7v237.3h45.2V273.4H101z" fill="white"/>
  </svg>
);

const TelegramLogo = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 1000 1000" fill="white">
    <path d="M226.3 494.7c145.8-63.5 243-105.4 291.6-125.6 138.9-57.8 167.7-67.8 186.5-68.1 4.1-.1 13.4 1 19.4 5.8 5.1 4.1 6.5 9.6 7.1 13.5s1.5 12.8.8 19.7c-7.5 79.1-40.1 270.9-56.6 359.5-7 37.5-20.8 50-34.2 51.3-29 2.7-51.1-19.2-79.2-37.6-44-28.8-68.9-46.8-111.6-75-49.4-32.5-17.4-50.4 10.8-79.6 7.4-7.6 135.3-124 137.8-134.6.3-1.3.6-6.2-2.3-8.8s-7.2-1.7-10.4-1c-4.4 1-74.7 47.5-210.9 139.4-20 13.7-38 20.4-54.2 20-17.9-.4-52.2-10.1-77.7-18.4-31.3-10.2-56.2-15.6-54-32.8 1.9-14.7 14.3-23.9 37.9-33.3z" fill="white"/>
  </svg>
);

const WebUILogo = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 40 40" fill="white">
    <path d="M20 28.4356C16.5306 28.4357 13.3035 30.2166 11.4521 33.1512L9.1543 36.7934L10.0371 37.3511C10.3132 37.5101 10.5937 37.6622 10.8779 37.8082L13.1436 34.2188C14.6285 31.8648 17.2171 30.437 20 30.4369C22.783 30.4369 25.3714 31.8647 26.8564 34.2188L29.1211 37.8082C29.4053 37.6623 29.6858 37.5101 29.9619 37.3511L30.8457 36.7934L28.5479 33.1512C26.6964 30.2165 23.4695 28.4356 20 28.4356ZM20.123 36.4428L20 36.4379C19.3855 36.4381 18.8239 36.774 18.5312 37.3072L18.4766 37.4166L17.3691 39.834C18.0662 39.9256 18.7744 39.9821 19.4922 40L20 38.8914L20.5068 40C21.2249 39.9821 21.9335 39.9256 22.6309 39.834L21.5244 37.4166L21.4697 37.3072C21.1966 36.8096 20.689 36.4842 20.123 36.4428ZM21 12.4063V11H19V12.4063L15.7891 0.422921L13.8574 0.940585L17.0674 12.923L10.8662 2.18005L9.13379 3.18021L15.335 13.9222L6.56543 5.15124L5.15039 6.56651L13.9199 15.3375L3.17969 9.13529L2.17969 10.868L12.9209 17.0702L0.94043 13.8597L0.422852 15.7917L12.4053 19.0031H12V21.0035H12.4053L0.422852 24.2149L0.94043 26.1469L12.9209 22.9354L2.17969 29.1386L3.17969 30.8713L13.9199 24.6681L5.15039 33.4401L6.56543 34.8554L13.1216 28.2964C13.684 27.7337 14 26.9706 14 26.175V20.435C14 17.1209 16.6865 14.4342 20 14.434C23.3137 14.434 26 17.1208 26 20.435V26.1759C26 26.9716 26.316 27.7347 26.8785 28.2974L33.4346 34.8554L34.8496 33.4401L26.0801 24.6691L36.8203 30.8713L37.8203 29.1386L27.0791 22.9354L39.0596 26.1469L39.5771 24.2149L27.5957 21.0035H40V19.0031H27.5947L39.5771 15.7917L39.0596 13.8597L27.0791 17.0692L37.8203 10.868L36.8203 9.13529L26.0781 15.3375L34.8496 6.56554L33.4355 5.15124L24.6641 13.9232L30.8662 3.18021L29.1338 2.18005L22.9316 12.923L26.1426 0.940585L24.2109 0.422921L21 12.4063Z" fill="white"/>
  </svg>
);

// ── Icon Map (inline SVG components) ──

const logoComponents: Record<string, React.FC<{ className?: string }>> = {
  orchestrator: ZoraLogo,
  qdrant: QdrantLogo,
  ollama: OllamaLogo,
  deepseek: DeepSeekLogo,
  postgres: PostgresLogo,
  docker: DockerLogo,
  '1c_odata': OneCLogo,
  telegram_bot: TelegramLogo,
  web_ui: WebUILogo,
};

const nodeGradients: Record<string, string> = {
  orchestrator: 'from-zora-accent to-zora-accent-light',
  qdrant: 'from-emerald-400 to-emerald-600',
  ollama: 'from-blue-400 to-blue-600',
  deepseek: 'from-purple-400 to-purple-600',
  postgres: 'from-cyan-400 to-cyan-600',
  web_ui: 'from-pink-400 to-pink-600',
  docker: 'from-orange-400 to-orange-600',
  '1c_odata': 'from-rose-400 to-rose-600',
  telegram_bot: 'from-sky-400 to-sky-600',
};

const statusDotColors: Record<string, string> = {
  healthy: 'bg-zora-green shadow-[0_0_8px_rgba(34,197,94,0.6)]',
  degraded: 'bg-zora-yellow shadow-[0_0_8px_rgba(245,158,11,0.6)]',
  down: 'bg-zora-red shadow-[0_0_8px_rgba(239,68,68,0.6)]',
  idle: 'bg-zora-gray shadow-[0_0_8px_rgba(107,114,128,0.4)]',
};

const shortDescriptions: Record<string, string> = {
  orchestrator: 'Центральный планировщик агентов',
  qdrant: 'Векторная БД для RAG-памяти',
  ollama: 'Локальный LLM-инференс',
  deepseek: 'Внешний LLM API (DeepSeek)',
  postgres: 'Реляционная БД истории',
  web_ui: 'Веб-интерфейс (FastAPI)',
  docker: 'Контейнеризация сервисов',
  '1c_odata': 'Интеграция с 1С по OData',
  telegram_bot: 'Telegram-уведомления',
};

// ── Orbit Node Component ──

function SystemOrbitNode({
  node,
  isCenter = false,
  floatDelay = 0,
}: {
  node: SystemGraphNode;
  isCenter?: boolean;
  floatDelay?: number;
}) {
  const gradient = nodeGradients[node.id] || 'from-zora-gray to-zora-gray/50';
  const LogoComponent = logoComponents[node.id];
  const size = isCenter ? 'w-24 h-24' : 'w-14 h-14';
  const iconSize = isCenter ? 'w-10 h-10' : 'w-6 h-6';

  const animClass = React.useMemo((): string => {
    if (isCenter) return 'animate-pulse-glow';
    switch (node.status) {
      case 'healthy': return 'animate-float-glow-green';
      case 'degraded': return 'animate-float-glow-yellow';
      case 'down': return 'animate-float-glow-red';
      default: return 'animate-float-glow-gray';
    }
  }, [node.status, isCenter]);

  const animStyle = React.useMemo((): React.CSSProperties => {
    if (isCenter) {
      return { boxShadow: '0 0 30px rgba(255,140,66,0.5)', animationDuration: '5s' };
    }
    let duration = '5s';
    if (node.status === 'degraded') duration = '3s';
    else if (node.status === 'down') duration = '1.5s';
    return { animationDuration: duration, animationDelay: `${floatDelay}s` };
  }, [node.status, isCenter, floatDelay]);

  return (
    <div className="flex flex-col items-center gap-1 group">
      <div
        className={`relative ${size} rounded-full bg-gradient-to-br ${gradient} flex items-center justify-center shadow-lg transition-shadow duration-300 group-hover:scale-110 ${animClass}`}
        style={animStyle}
      >
        {LogoComponent ? (
          <LogoComponent className={`${iconSize}`} />
        ) : (
          <span className={`${isCenter ? 'text-3xl' : 'text-lg'} text-white font-bold`}>
            {node.label?.charAt(0) || '?'}
          </span>
        )}
        {!isCenter && (
          <span
            className={`absolute -top-1 -right-1 w-3 h-3 rounded-full border-2 border-zora-bg ${
              statusDotColors[node.status] || 'bg-zora-gray'
            }`}
          />
        )}
      </div>
    </div>
  );
}

// ── Helper: compute orbit positions ──
function computeOrbitPositions(
  rx: number, ry: number,
  centerX: number, centerY: number,
  count: number,
  orbitAngle: number = 0
): { x: number; y: number }[] {
  if (count === 0) return [];
  return Array.from({ length: count }, (_, index) => {
    const angle = (index / count) * 2 * Math.PI - Math.PI / 2 + orbitAngle;
    return {
      x: centerX + rx * Math.cos(angle) - 28,
      y: centerY + ry * Math.sin(angle) - 28,
    };
  });
}

// ── Main Component ──

export default function SystemHealthGraph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setDims({ width, height });
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { data, isLoading } = useQuery({
    queryKey: ['systemGraph'],
    queryFn: getSystemGraph,
    refetchInterval: 30_000,
  });

  const [selectedNode, setSelectedNode] = useState<SystemGraphNode | null>(null);

  const apiNodes = useMemo(() => data?.nodes ?? [], [data]);

  const orchestrator = useMemo(
    () => apiNodes.find((n) => n.id === 'orchestrator'),
    [apiNodes]
  );
  const otherNodes = useMemo(
    () => apiNodes.filter((n) => n.id !== 'orchestrator'),
    [apiNodes]
  );

  const ellipseConfig = useMemo(() => {
    const w = dims.width;
    const h = dims.height;
    if (w === 0 || h === 0) {
      return { centerX: 200, centerY: 200, rx: 120, ry: 120 };
    }
    const centerX = w / 2;
    const centerY = h / 2;
    // Минимальный отступ от края контейнера до центра планеты — 38px.
    // Сама планета w-14 (56px), половина = 28px, итого ~10px воздух + запас на hover scale-110
    const rx = Math.max(centerX - 38, 60);
    const ry = Math.max(centerY - 38, 60);
    return { centerX, centerY, rx, ry };
  }, [dims]);

  // Статичные позиции планет (без вращения по орбите)
  const staticPositions = useMemo(
    () => computeOrbitPositions(ellipseConfig.rx, ellipseConfig.ry, ellipseConfig.centerX, ellipseConfig.centerY, otherNodes.length),
    [ellipseConfig.rx, ellipseConfig.ry, ellipseConfig.centerX, ellipseConfig.centerY, otherNodes.length]
  );

  const orbitRings = useMemo(() => {
    const { centerX, centerY, rx, ry } = ellipseConfig;
    return [0.5, 0.75, 1.0].map((scale) => ({
      cx: centerX,
      cy: centerY,
      rx: rx * scale,
      ry: ry * scale,
      opacity: scale * 0.25,
    }));
  }, [ellipseConfig]);

  return (
    <Card className="h-full border-border bg-card/50 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/50 shrink-0">
        <div className="flex items-center gap-2">
          <FiServer className="text-zora-accent" />
          <span className="text-sm font-semibold text-foreground">Граф компонентов</span>
        </div>
        <span className="text-[10px] text-muted-foreground">{apiNodes.length} компонентов</span>
      </div>

      <CardContent className="p-0 flex-1 min-h-[300px] relative overflow-hidden" ref={containerRef}>
        {isLoading ? (
          <div className="h-full flex items-center justify-center min-h-[300px]">
            <p className="text-muted-foreground text-sm">Загрузка графа...</p>
          </div>
        ) : (
          <div className="relative w-full h-full min-h-[300px]">
            <svg className="absolute inset-0 w-full h-full pointer-events-none">
              {orbitRings.map((ring, i) => (
                <ellipse
                  key={i}
                  cx={ring.cx}
                  cy={ring.cy}
                  rx={ring.rx}
                  ry={ring.ry}
                  fill="none"
                  stroke="rgba(255,140,66,0.22)"
                  strokeWidth={1 + i * 0.3}
                  strokeDasharray="6 4"
                  opacity={ring.opacity}
                />
              ))}
              {otherNodes.map((node, i) => {
                const pos = staticPositions[i];
                if (!pos) return null;
                const isHealthy = node.status === 'healthy';
                const lineColor = isHealthy
                  ? 'rgba(34,197,94,0.55)'
                  : node.status === 'degraded'
                  ? 'rgba(245,158,11,0.45)'
                  : 'rgba(239,68,68,0.45)';
                return (
                  <line
                    key={`line-${node.id}`}
                    x1={pos.x + 28}
                    y1={pos.y + 28}
                    x2={ellipseConfig.centerX}
                    y2={ellipseConfig.centerY}
                    stroke={lineColor}
                    strokeWidth={isHealthy ? 2 : 1.2}
                    strokeDasharray={isHealthy ? '4 3' : '3 4'}
                    className={isHealthy ? 'animate-dash-flow' : ''}
                    opacity={isHealthy ? 1 : 0.65}
                  />
                );
              })}
            </svg>

            <div
              className="absolute z-10 animate-float"
              style={{
                left: ellipseConfig.centerX - 48,
                top: ellipseConfig.centerY - 48,
                animationDuration: '5s',

              }}
            >
              <SystemOrbitNode
                node={
                  orchestrator || {
                    id: 'orchestrator',
                    label: 'ZORA Core',
                    type: 'service',
                    status: 'healthy',
                  }
                }
                isCenter
              />
            </div>

            {otherNodes.map((node, index) => {
              const pos = staticPositions[index];
              if (!pos) return null;
              return (
                <div
                  key={node.id}
                  className="absolute cursor-pointer transition-transform hover:scale-110 z-10"
                  style={{
                    left: pos.x,
                    top: pos.y,
                    filter:
                      node.status === 'healthy'
                        ? 'drop-shadow(0 0 8px rgba(34,197,94,0.3))'
                        : 'none',
                  }}
                  onClick={() =>
                    setSelectedNode((prev) =>
                      prev?.id === node.id ? null : node
                    )
                  }
                >
                  <SystemOrbitNode node={node} floatDelay={index * 0.35} />
                </div>
              );
            })}
          </div>
        )}
      </CardContent>

      {selectedNode && (
        <div className="border-t border-border/50 p-2.5 bg-background/50 shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-sm font-semibold text-foreground whitespace-nowrap">
                {selectedNode.label}
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-background text-muted-foreground border border-border whitespace-nowrap">
                {selectedNode.id}
              </span>
              <span className="text-[10px] text-muted-foreground truncate hidden sm:inline">
                {shortDescriptions[selectedNode.id] || '...'}
              </span>
            </div>
            <div className="flex items-center gap-2 shrink-0 ml-2">
              {selectedNode.metrics && (
                <div className="flex items-center gap-2 text-[10px]">
                  {Object.entries(selectedNode.metrics).map(([key, val]) => (
                    <span key={key} className="text-muted-foreground whitespace-nowrap">
                      <span className="text-muted-foreground">{key}:</span>{' '}
                      <span className="text-foreground font-medium">
                        {typeof val === 'number' ? val.toFixed(2) : val}
                      </span>
                    </span>
                  ))}
                </div>
              )}
              <span
                className={`w-2 h-2 rounded-full ${
                  statusDotColors[selectedNode.status] || 'bg-zora-gray'
                }`}
              />
              <button
                onClick={() => setSelectedNode(null)}
                className="text-muted-foreground hover:text-foreground text-xs ml-1"
              >
                ✕
              </button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
