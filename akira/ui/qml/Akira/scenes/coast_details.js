.pragma library
.import "pixel.js" as P

// Small stories at the edges of Driftwood Bay. Colours come from the parent
// painting, including its upper-right light, seasonal tint and weather grade.
// The hooks below follow paint depth: distant shore -> sea -> land -> near life.
function lighthouse(p, base, shoreColor, pale, night, frame) {
    var x=350, dark=P.mix(shoreColor,"#293f4b",0.24);
    p.ellipse(x-2,base+1,6,1,dark);
    p.poly([[x-2,base],[x-1,base-12],[x+2,base-12],[x+3,base]],P.mix(shoreColor,pale,0.34));
    p.line(x+2,base-11,x+3,base,P.mix(shoreColor,pale,0.58));
    p.rect(x-1,base-7,4,2,P.mix(shoreColor,"#91675c",0.24));
    p.rect(x-2,base-13,6,1,dark);
    p.rect(x-1,base-16,4,3,dark);
    p.rect(x,base-15,2,2,night>0.2?P.mix("#839794","#e5c394",[0.48,0.62,0.76,0.62][frame]):pale);
    p.poly([[x-3,base-16],[x+1,base-19],[x+4,base-16]],dark);
    // A low keeper's shed sits on the same terrain, with no isolated bright beam.
    p.rect(x+4,base-4,6,4,shoreColor);
    p.line(x+3,base-5,x+10,base-5,dark);
}

function seaSecret(p, sea, foam, night, frame) {
    if(night<0.25) return;
    // Three almost-submerged contours behind the surface ripples. They could
    // pass for rocks until one follows the direction of the articulated limbs.
    var low=P.mix(sea,"#162b39",0.15+night*0.10), rim=P.mix(low,sea,0.68);
    p.ellipse(364,166,5,2,low);
    var curls=[[[359,166],[355,165],[354,162],[356,160]],
               [[366,166],[370,163],[370,159],[373,157]],
               [[367,167],[374,166],[377,162],[380,162]]];
    for(var i=0;i<curls.length;i++) for(var j=0;j<curls[i].length-1;j++) {
        var a=curls[i][j],b=curls[i][j+1];
        p.line(a[0],a[1],b[0],b[1],low);
    }
    p.dot(369,163,rim);
    p.rect(352+[0,1,2,1][frame],167,14,1,sea);
    p.rect(365,166,15,1,P.mix(sea,foam,0.08));
    p.rect(357,169,19,1,P.mix(sea,foam,0.12));
}

function jetty(p,c,winter) {
    // The bank is at y=211 here. The near end rests on land; both seaward
    // supports reach below the planks. Trees later occlude the right-hand end.
    p.line(396,201,397,208,c.shadow);
    p.line(402,208,403,215,c.shadow);
    p.poly([[394,199],[399,198],[412,219],[403,222]],c.bark);
    p.poly([[395,199],[399,199],[411,218],[404,220]],P.mix(c.wood,c.rockLight,0.30));
    for(var i=0;i<6;i++) p.line(395+i*1.5,201+i*3,400+i*1.8,200+i*3,c.bark);
    p.line(399,198,411,218,winter?c.snow:P.mix(c.wood,c.cream,0.27));
    p.line(395,200,395,196,c.bark);
    p.line(405,219,405,213,c.bark);
    p.line(395,196,405,213,P.mix(c.wood,c.cream,0.18));
}

function cottage(p,c,season,night,wx,frame,sea,tone) {
    var winter=season==="winter";
    // Window boxes don't alter the repaired gable, fascia or chimney overlap.
    if(season==="spring"||season==="summer") for(var box=0;box<2;box++) {
        var x=108+box*15;
        p.rect(x,215,5,2,c.bark);p.rect(x+3,215,2,1,c.wood);
        p.rect(x,214,5,1,c.pine[1]);
        p.dot(x+1,213,tone(season==="spring"?"#e3bac7":"#d8c48d"));
        p.dot(x+4,213,tone("#b7b6d0"));
    }
    // A bench beside the porch. All its contact shadows fall to the left.
    p.ellipse(148,226,9,1,c.castShadow);
    p.rect(141,218,15,2,c.bark);p.rect(142,218,14,1,c.wood);
    p.rect(141,224,16,1,c.wood);p.rect(142,222,1,5,c.bark);p.rect(154,222,1,5,c.bark);
    if(winter) {
        p.rect(141,217,15,1,c.snow);p.rect(142,223,14,1,c.snow);
        p.line(101,205,101,208,c.snow);p.line(133,205,133,209,c.snow);
    } else if(season!=="autumn") {
        p.rect(147,222,5,2,tone("#798c9a"));p.rect(148,223,4,1,c.cream);
    }
    if(winter||night>0.2||wx.gloom>0.4) {
        var smoke=P.mix(sea,c.foam,wx.wind>0.6?0.16:0.26);
        for(var puff=0;puff<5;puff++) {
            var dx=[0,1,0,-1][frame]*(puff%2)+wx.wind*puff*1.8;
            p.rect(126+dx,184-puff*3,2+puff%3,1,smoke);
        }
    }
}

function spring(p,c,frame,wx,tone) {
    // Petals have landed beneath the canopy, not across the whole picture.
    for(var i=0;i<24;i++) {
        var x=13+P.hash(i*17+351)*66, y=239+P.hash(i*29+501)*20;
        p.rect(x,y,1+i%2,1,P.mix(c.grass,tone("#e7bfc9"),0.58));
    }
    // A tiny nesting bird on a branch that visibly meets the trunk.
    p.line(31,231,41,220,c.bark);p.line(36,225,45,226,c.bark);
    p.ellipse(43,226,3,1,c.wood);p.line(40,225,46,225,c.cream);
    p.ellipse(43,223,2,1,tone("#a18a77"));p.dot(45,221,c.bark);
    if(wx.wind<0.6 && wx.precip===0) {
        var wing=[2,1,0,1][frame];
        p.line(192,234,192,236,c.bark);
        p.rect(190,234-wing,2,1+wing,tone("#d8c497"));
        p.rect(193,234-wing,2,1+wing,c.cream);
    }
}

function summer(p,c,wx,night,frame,tone) {
    // A small sandcastle and bucket occupy the dry beach between the parasols.
    p.ellipse(291,240,6,1,c.sandShadow);
    p.rect(287,234,3,6,c.sandShadow);p.rect(292,234,3,6,c.sandShadow);
    p.rect(289,236,4,4,c.sand);p.rect(288,233,1,2,c.sand);p.rect(293,233,1,2,c.sand);
    p.rect(290,238,2,2,c.sandShadow);p.line(294,231,294,235,c.wood);
    if(wx.wind<0.6) p.line(294,231,297,232,tone("#b87b6c"));
    p.rect(265,234,3,3,tone("#8aabb3"));p.line(265,233,267,233,c.sandShadow);
    p.line(270,232,269,237,c.wood);
    p.dot(320,231,c.cream);p.rect(321,232,2,1,c.sandShadow);
    p.dot(359,221,c.cream);p.dot(361,220,c.cream);
    // Five subdued fireflies cluster near the oak after dark, out of the text.
    if(night>0.2 && wx.precip===0 && wx.wind<0.6) for(var i=0;i<5;i++) {
        var x=52+P.hash(i+972)*38,y=224+P.hash(i+634)*17;
        p.dot(x,y,P.mix(c.grass,tone("#e9d89b"),[0.4,0.65,0.82,0.65][(frame+i)%4]));
    }
}

function autumn(p,c,night,frame,tone) {
    for(var leaf=0;leaf<30;leaf++) {
        var lx=19+P.hash(leaf*13+648)*54,ly=237+P.hash(leaf*7+195)*22;
        p.line(lx,ly,lx+1,ly+1,P.mix(c.grass,c.leaf[leaf%3],0.68));
    }
    for(var mushroom=0;mushroom<3;mushroom++) {
        var mx=61+mushroom*5,my=251+mushroom%2*3;
        p.line(mx,my,mx,my-3,c.cream);
        p.ellipse(mx,my-3,2,1,tone("#9f6457"));p.dot(mx+1,my-4,c.sand);
    }
    // A weathered notice on the oak: three pixels suggest a missing face.
    p.rect(30,232,3,5,P.mix(c.bark,c.sand,0.52));
    p.dot(31,233,c.bark);p.rect(31,235,2,1,P.mix(c.bark,c.sand,0.22));
    // An unplugged CRT on the bench. Quiet scanlines, not whole-scene glitches.
    p.line(148,216,146,213,c.bark);p.line(149,216,152,213,c.bark);
    p.rect(144,216,10,7,c.bark);p.rect(145,217,7,5,P.mix(c.window,c.shadow,0.42));
    var phosphor=P.mix(c.window,c.cream,night>0.25?0.31:0.1);
    p.rect(146,218,5,1,phosphor);p.rect(145+(frame%2),220,5,1,P.mix(phosphor,c.bark,0.34));
    p.dot(153,221,tone("#a67863"));p.rect(146,223,6,1,c.bark);
    // A mask-sized pale mark, half blocked by the pine. The body remains in
    // its existing shadow; it neither lunges nor blinks into the scene.
    if(night>0.35) {
        p.rect(435,217,2,2,P.mix(c.pine[0],c.cream,0.19));
        p.dot(435,217,c.pine[0]);
        // One jack-o'-lantern instead of turning the whole patch into faces.
        var ember=P.mix(tone("#bc793c"),"#cda068",0.38);
        p.dot(86,224,ember);p.dot(89,224,ember);p.rect(87,226,2,1,ember);
    }
}

function winter(p,c,tone) {
    // Runner sled resting in the snow next to the cottage path.
    p.ellipse(76,246,9,1,c.castShadow);
    p.line(72,244,84,244,c.bark);p.line(73,246,85,246,c.bark);
    p.line(84,244,86,242,c.bark);p.line(85,246,87,244,c.bark);
    p.rect(74,239,9,3,tone("#a06e61"));
    p.line(75,240,75,244,c.bark);p.line(82,240,82,244,c.bark);
    p.line(77,239,79,231,c.wood);p.rect(73,238,10,1,c.snow);
    // Small tracks stop at the snowman's feet; they avoid the beach/water.
    for(var step=0;step<7;step++) {
        var x=145+step*5,y=255-step*1.1;
        p.rect(x,y,2,1,c.grassDark);p.rect(x+1,y+3,2,1,c.grassDark);
    }
    // A robin uses the sunward rock edge as a perch.
    p.line(387,239,387,242,c.bark);
    p.ellipse(387,238,2,2,c.bark);p.dot(388,238,tone("#b78065"));
    p.dot(389,236,c.bark);p.dot(390,237,c.sand);
}
